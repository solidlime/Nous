"""矛盾整理・未解決の問い（conflicts）— WikiWorker から移設した mixin。

計画書: ``docs/archive/superpowers/plans/2026-11-07-wiki-dreaming.md`` の矛盾整理パート。

``WikiWorker`` が継承する。``_cfg`` と ``_record_event`` / ``_write_research`` はホスト
（``WikiWorker``）側が提供する。移設のみでロジックは変えていない。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nous.application.wiki.questions import (
    close_open_questions,
    dedupe_open_questions,
    find_open_questions,
    question_key_of,
    question_pair_key,
    question_query_key,
    source_context_for,
)
from nous.application.wiki.research import research
from nous.domain.shared.result import Failure
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.config.settings import WikiConfig
    from nous.infrastructure.wiki.store import WikiStore

logger = get_logger(__name__)


# ------------------------------------------------------------------
# 矛盾整理（#39）— wiki 層は編纂応答の conflicts、記憶層は週次掃除
# ------------------------------------------------------------------


class ConflictsMixin:
    """編纂応答の矛盾整理と未解決の問いの管理（``WikiWorker`` の mixin）。"""

    if TYPE_CHECKING:
        # ホスト（WikiWorker）が提供する属性・メソッドの型宣言（mixin 公式パターン）。
        _cfg: WikiConfig

        def _record_event(
            self, ctx, persona: str, summary: str, detail: dict | None, *, event_type: str = ...
        ) -> None: ...

        def _write_research(self, ctx, persona: str, store: WikiStore, found: dict[str, dict]) -> None: ...

    def _resolve_questions(self, ctx, persona: str, store: WikiStore, questions: list[dict]) -> None:
        """問いを調査してページ末尾に根拠を足す。書込みは slug ごとに 1 回だけ。

        調査の前にページの存在を確かめる（存在しない slug に LLM を焼かない）。
        失敗・ツール無しは監査 1 行に留め、編纂結果には触らない（fail-safe）。
        """
        cfg = self._cfg
        if not cfg.research_enabled or not questions:
            return
        found: dict[str, dict] = {}
        no_tools = False
        for item in questions[: max(0, cfg.max_research_per_cycle)]:
            query = str(item.get("query") or "").strip()
            if not query:
                continue
            slug = str(item.get("topic") or "persona")
            page_result = store.read_page(slug)
            if isinstance(page_result, Failure):
                self._record_event(
                    ctx,
                    persona,
                    f"skipped: research target {slug} not found",
                    {"slug": slug, "question": query[:200]},
                    event_type="wiki.research",
                )
                continue
            try:
                result = asyncio.run(research(ctx, persona, query, max_calls=cfg.research_max_tool_calls))
            except Exception as e:  # noqa: BLE001 — worker を落とさない
                logger.warning("WikiWorker: research failed: %s", e)
                result = {"reason": "failed"}
            reason = str(result.get("reason") or "")
            if reason == "no_tools":
                no_tools = True
                continue
            if reason:
                # 「ツールが無い」と「調べたが失敗した」を混ぜない（監査が嘘をつく）。
                self._record_event(
                    ctx,
                    persona,
                    f"warning: research failed for {query[:60]}: {reason}",
                    {"question": query, "topic": slug, "reason": reason},
                    event_type="wiki.research",
                )
                continue
            entry = found.setdefault(slug, {"page": page_result.value, "hits": []})
            entry["hits"].extend(result["hits"])
            self._record_event(
                ctx,
                persona,
                f"research {len(result['hits'])} hits for {query[:60]}",
                {
                    "question": query,
                    "topic": slug,
                    "tool": result["tools"][-1] if result["tools"] else "",
                    "tools": result["tools"],
                    "calls": result["calls"],
                    "hits": [str(h.get("url", "")) for h in (result.get("hits") or []) if isinstance(h, dict)],
                    "answer": result["answer"][:1000],
                },
                event_type="wiki.research",
            )
        if no_tools:
            self._record_event(
                ctx, persona, "skipped: no mcp tool", {"questions": len(questions)}, event_type="wiki.research"
            )
        self._write_research(ctx, persona, store, found)

    def _apply_conflicts(
        self,
        ctx,
        persona: str,
        conflicts: list[dict],
        questions: list[dict],
        *,
        store: WikiStore,
        topic: str,
        known_slugs: set[str],
    ) -> None:
        """編纂応答の ``conflicts`` / ``questions`` を処理する（追加 LLM 呼び出しなし）。

        resolved=true は本文で経緯を書き直し済みなので監査だけ残す。false は
        ``open-question`` として記憶に置き、日記の「未解決」から拾えるようにする。
        """
        for item in conflicts:
            a = str(item.get("a") or "").strip()
            b = str(item.get("b") or "").strip()
            detail = str(item.get("detail") or "").strip()
            if not (a and b and detail):
                continue
            unknown = [slug for slug in (a, b) if slug not in known_slugs]
            if unknown:
                # 幻覚 slug を記憶に落とさない（存在しないページの矛盾は存在しない）。
                self._record_event(
                    ctx,
                    persona,
                    f"skipped: conflict references unknown page {unknown[0]}",
                    {"topic": topic, "a": a, "b": b},
                    event_type="wiki.conflict",
                )
                continue
            resolved = bool(item.get("resolved"))
            key = question_pair_key(a, b, str(item.get("kind") or ""))
            self._record_event(
                ctx,
                persona,
                f"conflict {'resolved' if resolved else 'open'}: {a} / {b}",
                {"topic": topic, "a": a, "b": b, "kind": str(item.get("kind") or ""), "detail": detail[:300]},
                event_type="wiki.conflict",
            )
            if not resolved:
                self._record_open_question(
                    ctx,
                    persona,
                    f"{a} と {b}: {detail}",
                    topic=topic,
                    project=self._page_project(store, a),
                    key=key,
                )
            else:
                self._close_open_question(ctx, persona, key, topic=topic)

        for item in questions:
            query = str(item.get("query") or "").strip()
            if not query:
                continue
            why = str(item.get("why") or "").strip()
            target = str(item.get("topic") or topic).strip() or topic
            self._record_open_question(
                ctx,
                persona,
                f"{query}（理由: {why}）" if why else query,
                topic=target,
                project=self._page_project(store, target),
                key=question_query_key(target, query),
            )

    @staticmethod
    def _page_project(store: WikiStore, slug: str) -> str | None:
        """ページの frontmatter から project を引く（引けなければ None）。

        topic 文字列から逆算すると ``project:nous-arch`` のような幻の project タグが
        生まれ、そのタグの群が永遠に孤立する。
        """
        try:
            page = store.read_page(slug)
        except Exception:  # noqa: BLE001 — タグが付かないだけで害は無い
            return None
        if isinstance(page, Failure):
            return None
        project = getattr(page.value, "project", None)
        return str(project) if project else None

    def _dedupe_open_questions(self, ctx, persona: str) -> None:
        """溜まった未解決の問いを本文の正規化で畳み、上限まで削る（#55）。"""
        cap = max(1, int(self._cfg.max_open_questions))
        try:
            deleted, remaining = asyncio.run(dedupe_open_questions(ctx, persona, cap=cap))
        except Exception:
            logger.warning("WikiWorker: open-question dedupe failed", exc_info=True)
            return
        if deleted:
            self._record_event(
                ctx,
                persona,
                f"open questions deduped: {deleted} removed ({remaining} left)",
                {"removed": deleted, "remaining": remaining},
                event_type="wiki.conflict",
            )

    def _close_open_question(self, ctx, persona: str, key: str, *, topic: str) -> int:
        """解消した問いを閉じる（Zero Inbox: 消す）。"""
        try:
            closed = asyncio.run(close_open_questions(ctx, persona, key))
        except Exception as e:  # noqa: BLE001 — worker を落とさない
            logger.warning("WikiWorker: close open question failed: %s", e)
            closed = 0
        if closed:
            self._record_event(
                ctx,
                persona,
                f"question closed: {key}",
                {"topic": topic, "key": key, "closed": closed},
                event_type="wiki.conflict",
            )
        return closed

    def _record_open_question(
        self, ctx, persona: str, question: str, *, topic: str, project: str | None = None, key: str
    ) -> None:
        """未解決の問いを記憶に 1 件置く（正規化キーで重複を抑止、#55）。

        キーは「何についての問いか」だけで決まる（:mod:`nous.application.wiki.questions`）。
        上限 ``max_open_questions`` を超えたら新規作成しない。
        失敗を無言で潰さない: ``create_memory`` は意味的重複（>=0.75）で
        ``DuplicateMemoryError`` を返すので、監査に理由を残す。
        """
        try:
            existing = self._open_questions(ctx)
        except Exception:
            logger.debug("WikiWorker: open-question lookup failed", exc_info=True)
            existing = []
        for memory in existing:
            if question_key_of(memory) == key:
                return  # 同じ問いは一度だけ（毎サイクル増やさない）
        cap = max(1, int(self._cfg.max_open_questions))
        if len(existing) >= cap:
            self._record_event(
                ctx,
                persona,
                f"skipped: open-question cap reached ({cap})",
                {"topic": topic, "key": key, "open": len(existing)},
                event_type="wiki.conflict",
            )
            return

        tags = ["open-question"] if project is None else [f"project:{project}", "open-question"]
        try:
            result = asyncio.run(
                ctx.memory_service.create_memory(
                    content=question[:1200],
                    importance=0.5,
                    emotion="neutral",
                    emotion_intensity=0.0,
                    tags=tags,
                    privacy_level="private",
                    source_context=source_context_for(key),
                    kind="semantic",
                    source_type="llm_inferred",
                )
            )
        except Exception as e:  # noqa: BLE001 — worker を落とさない
            logger.warning("WikiWorker: failed to record open question: %s", e)
            self._record_event(
                ctx,
                persona,
                f"warning: open question not recorded: {e}",
                {"topic": topic, "reason": str(e)[:200]},
                event_type="wiki.conflict",
            )
            return
        if isinstance(result, Failure):
            self._record_event(
                ctx,
                persona,
                f"warning: open question not recorded: {result.error}",
                {"topic": topic, "reason": str(result.error)[:200]},
                event_type="wiki.conflict",
            )
            return
        self._record_event(
            ctx,
            persona,
            f"question recorded: {question[:60]}",
            {"topic": topic, "project": project, "key": key},
            event_type="wiki.conflict",
        )

    @staticmethod
    def _open_questions(ctx) -> list:
        return find_open_questions(ctx)
