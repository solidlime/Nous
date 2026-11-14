"""WikiWorker — ドリーミング（wiki 編纂）worker。

計画書: ``docs/archive/superpowers/plans/2026-11-07-wiki-dreaming.md`` §4.2。

記憶の整理は **consolidation（時間軸 gist）→ wiki（トピック編纂）** の 2 段で動く:

- SELECT: persona の active 記憶を ``project:*`` タグでクラスタに分ける
  （タグ無しは ``persona`` クラスタ）。cycle ごとに上位 ``topics_per_cycle`` 件。
- 編纂: クラスタの記憶（本文 preview）+ 既存 wiki ページ目次を LLM に渡し、
  wiki ページ（slug/title/body/sources/delete）を JSON で受け取る。
- 適用: ``WikiStore.write_page`` でファイル層（正）を書き、Qdrant 索引
  （collection prefix ``wiki_``）を body_hash 変化時のみ更新する。
- 監査: ページ毎に session_events へ 1 行（``wiki.compiled``）。失敗は
  ``error: ...`` 行として記録し、ファイルは変えない（fail-safe）。
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING

from nous.application.wiki import vector_index
from nous.application.wiki.conflicts import ConflictsMixin
from nous.application.wiki.journal import (
    _CONTENT_PREVIEW_CHARS,
    _JOURNAL_SLUG_PREFIX,
    JournalMixin,
    _hash_of,
    _parse_json_object,
)
from nous.domain.shared.result import Failure, Success
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.wiki.store import INDEX_SLUG, render_page

if TYPE_CHECKING:
    from collections.abc import Iterable

    from nous.config.settings import Settings, WikiConfig
    from nous.domain.memory.entities import Memory
    from nous.infrastructure.llm.base import LLMProvider
    from nous.infrastructure.wiki.store import WikiPage, WikiStore

logger = get_logger(__name__)

#: 編纂対象クラスタの最小記憶数（これ未満の topic はページ化しない）。
MIN_TOPIC_MEMORIES = 3

_GIST_DUMP_SUBDIR = "_purged"  # 旧 gist を消す前の退避先（<persona>/wiki/_purged/）
_EVENT_KEY_SAMPLE = 50  # 監査イベントに載せるキーの見本数（全件は DB を膨らませる）

#: 既存ページ目次で LLM に渡す本文プレビュー長（編纂対象外のページ）。
_PAGE_PREVIEW_CHARS = 400

_WIKI_PROMPT = """あなたは長期記憶を編纂する司書です。以下の記憶クラスタと既存 wiki ページを読み、
wiki ページ（Markdown 本文）を作成または改訂してください。

現在時刻: {now}
クラスタ: {topic}

編纂ルール:
- 記憶の**列挙ではなく統合**。同じ事柄の記憶は 1 段落にまとめ、矛盾する記憶は
  「以前は X、現在は Y」と経緯で書く（矛盾を消さない）。
- 見出し・箇条書きを使い、抽象度の高い要約にする（本文は {max_bytes} バイト以内）。
- 関連ページへは本文中で [[slug]] 形式の wikilink を張る（存在しない slug でもよい。
  参照先は作成され次第リンクになる）。
- slug は `{slug_prefix}` で始まる小文字英数とハイフンのみ。既存ページを改訂する場合は
  既存 slug をそのまま使う。新規トピックを分けたい場合のみ新しい slug を提案する。
- `days_since_update` が {stale_days} 以上のページは**今回必ず改訂する**（古いまま残さない）。
- 既存ページを改訂する場合は**``body`` の全文が渡されている**。古い記述を残したまま
  追記しない。記憶のほうが新しいのに現在形で残っている記述は書き直す。
- 「訂正の節を足す」だけの改訂はしない。食い違っている**その文自体**を書き換える
  （例: 手順の列挙に廃止済みの要素が混じっていたら、列挙から外す）。節を足すと
  同じページの中で現在形が 2 通りになり、どちらが今なのか読めなくなる。
- 記憶には ``when``（その記憶が書かれた日）が付いている。同じ事柄の記憶が複数あるときは
  ``when`` の新しいほうが現在の状態。
- **sources には必ず上記記憶リストの key だけを入れる**（存在しない key は捨てられる）。
- 旧ページを統合して不要になった場合のみ delete にその slug を入れる。
{conflict_instructions}

既存 wiki ページ:
{pages}

記憶リスト:
{memories}

以下の JSON のみを返してください（説明文は不要）:
{{"pages": [{{"slug": "...", "title": "...", "body": "Markdown本文", "sources": ["<memory key>", ...], "delete": ["<slug>", ...]}}],
 "conflicts": [{{"a": "<slug>", "b": "<slug>", "kind": "value|fact|scope", "detail": "何がどう食い違うか", "resolved": true}}],
 "questions": [{{"query": "外部で確かめたいこと", "why": "なぜ必要か", "topic": "<slug>"}}]}}
（conflicts / questions が無い場合は空配列）
"""


_CONFLICT_ON = """- 既存ページ同士で内容が食い違っている箇所を見つけたら conflicts に書く。
  本文で「以前は X、現在は Y」と経緯を書いて解消したものは resolved=true、
  決められなかったものは resolved=false（後で外部で確かめる候補になる）。
- 外部で確かめないと決められない事項は questions に書く（推測で埋めない）。"""

#: ``conflict_check_enabled=false`` のとき。schema は残す（JSON の形を変えない）。
_CONFLICT_OFF = """- conflicts / questions は今回使わない。どちらも空配列で返す。"""


class WikiWorker(JournalMixin, ConflictsMixin):
    """wiki 編纂 worker（常駐 thread + graceful shutdown）。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        cfg: WikiConfig = settings.wiki
        self._cfg = cfg
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        #: 定刻に persona コンテキストが空だった時の再試行回数と間隔（1 日を空振りで捨てない）。
        self._empty_retries = 30
        self._retry_seconds = 60.0
        #: サイクル内で error イベントが出た件数。0 より大きければ定刻を待たず短くリトライする。
        self._cycle_errors = 0
        #: 直近の LLM 呼び出しの計器（attempt/max_tokens/text_len/stream_error）。監査イベントに載せる。
        self._last_llm: dict | None = None
        #: テスト用: False にすると Qdrant 索引更新を行わない（既定は有効）。
        self.vector_enabled = True

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    #: 1 サイクルで LLM を呼ぶ最大回数（2 回目は予算 2 倍）。
    _llm_attempts = 2
    #: 1 回目の max_tokens。reasoning モデルでも本文を書き切れる余裕を取る。
    _max_tokens = 16000
    #: サイクルが失敗したときの再試行間隔（秒）。1 回の一時障害で 24h 空くのを防ぐ。
    _error_retry_seconds = 1800.0

    def start(self) -> None:
        if self._running:
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="wiki-worker")
        self._thread.start()
        logger.info(
            "WikiWorker started (at_hour=%d %s interval=%ds topics=%d)",
            self._cfg.run_at_hour,
            self._cfg.run_at_tz,
            self._cfg.interval_seconds,
            self._cfg.topics_per_cycle,
        )
        if self._cfg.run_at_hour >= 0:
            logger.info("WikiWorker next run in %.0fs", self._next_delay())

    def stop(self, timeout: float = 5.0) -> None:
        self._running = False
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("WikiWorker stopped")

    def _run(self) -> None:
        first = True
        retry_now = False
        while not self._stop_event.is_set():
            scheduled = self._cfg.run_at_hour >= 0
            # 定刻方式は常に待つ。interval 方式は従来どおり初回だけ即実行する。
            # 失敗直後は「翌日」ではなく短間隔（_error_retry_seconds）だけ待って回し直す。
            delay = self._error_retry_seconds if retry_now else self._next_delay() if scheduled or not first else 0.0
            retry_now = False
            first = False
            if delay > 0 and self._stop_event.wait(delay):
                return  # 停止指示
            if scheduled:
                # 定刻に persona コンテキストが空（初リクエスト前）なら、1 日捨てずに短間隔で再試行する。
                for _ in range(self._empty_retries):
                    if self._stop_event.is_set() or self._has_contexts():
                        break
                    if self._stop_event.wait(self._retry_seconds):
                        return
            try:
                self._cycle_errors = 0
                self.run_cycle()
            except Exception:
                logger.exception("Wiki cycle failed")
            if scheduled and self._cycle_errors:
                # 一時障害で丸 1 日空くのを防ぐ。失敗があれば 30 分後に再挑戦する。
                logger.warning(
                    "WikiWorker: %d topic(s) failed — retrying in %.0fs instead of a full day",
                    self._cycle_errors,
                    self._error_retry_seconds,
                )
                retry_now = True

    def _next_delay(self) -> float:
        """次サイクルまでの待ち秒数。

        ``run_at_hour >= 0`` なら毎日その時刻（``run_at_tz``、既定 Asia/Tokyo の 03:00）に
        走らせる。``-1`` なら旧来の「前サイクル終了から interval_seconds 後」。
        コンテナの TZ には依存しない（UTC 運用でも 03:00 JST になる）。
        """
        if self._cfg.run_at_hour < 0:
            return float(self._cfg.interval_seconds)
        from nous.domain.shared.time_utils import get_now

        try:
            now = get_now(self._cfg.run_at_tz)
        except Exception:
            logger.warning(
                "WikiWorker: unknown run_at_tz %r — falling back to UTC",
                self._cfg.run_at_tz,
            )
            now = datetime.now(UTC)  # ZoneInfo を再参照しない（tzdata 不在時に同じ例外を踏む）
        target = now.replace(hour=self._cfg.run_at_hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    @staticmethod
    def _has_contexts() -> bool:
        """persona コンテキストが 1 つでも生成済みか（遅延生成なので起動直後は空）。"""
        from nous.application.use_cases import AppContextRegistry

        try:
            return bool(AppContextRegistry._contexts)
        except Exception:
            logger.debug("WikiWorker: context registry unavailable", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # 1 cycle
    # ------------------------------------------------------------------

    def run_cycle(self) -> None:
        """1 cycle 実行（手動運転・検証用に public）。enabled=False なら何もしない。"""
        if not self._cfg.enabled:
            logger.debug("WikiWorker disabled, skip")
            return
        from nous.application.use_cases import AppContextRegistry

        try:
            personas = list(AppContextRegistry._contexts.keys())
        except Exception:
            logger.exception("WikiWorker: failed to list personas")
            return

        for persona in personas:
            try:
                ctx = AppContextRegistry.get(persona)
                self._compile_persona(ctx, persona)
            except Exception:
                logger.exception("WikiWorker: error for persona=%s", persona)

    # ------------------------------------------------------------------
    # SELECT
    # ------------------------------------------------------------------

    def _select_topics(
        self, memories: list[Memory], now: datetime, store: WikiStore, persona: str
    ) -> list[tuple[str, list[Memory]]]:
        """クラスタ（topic slug, 記憶リスト）を返す。cycle 上限 topics_per_cycle 件。

        優先度: 最後に編纂された時刻が古い順（未編纂は最優先）→ 記憶数降順。
        """
        buckets: dict[str, list[Memory]] = {}
        for m in memories:
            if m.lifecycle_status != "active":
                continue
            if getattr(m, "source_type", "") == "consolidated":
                continue
            buckets.setdefault(_topic_of(m), []).append(m)

        last_compiled = self._last_compiled(store)
        # 既にページのある topic は新着 1 件でも巡回対象にする。編纂で源を物理削除すると
        # active が減り、MIN_TOPIC_MEMORIES の下限でその topic が永久に選ばれなくなるため。
        topics = [
            (slug, mems)
            for slug, mems in buckets.items()
            if len(mems) >= (1 if slug in last_compiled else MIN_TOPIC_MEMORIES)
        ]
        # 並び順: 最後に編纂された時刻が古い順（未編纂は "" で最優先）
        # → 同順位は記憶数降順。これで小クラスタにも巡回が回る。
        topics.sort(key=lambda item: (last_compiled.get(item[0], ""), -len(item[1])))
        selected = topics[: self._cfg.topics_per_cycle]
        return [(slug, self._most_recent(mems)) for slug, mems in selected]

    def _last_compiled(self, store: WikiStore) -> dict[str, str]:
        """topic → 最後に編纂された時刻（ページ updated の最大値）。"""
        latest: dict[str, str] = {}
        for page in store.list_pages():
            if page.slug.startswith(_JOURNAL_SLUG_PREFIX) or not page.sources or not page.updated:
                continue
            topic = _topic_of_page(page)
            if page.updated > latest.get(topic, ""):
                latest[topic] = page.updated
        return latest

    def _delete_sources(self, ctx, persona: str, sources: Iterable[str], seen: set[str]) -> int:
        """編纂に消化された源記憶を物理削除する（Wiki が正本。inbox には残さない）。

        同じ key を複数ページ／日記が引用しうるので ``seen`` で cycle 内の二重計上を防ぐ。
        失敗したキーは ``seen`` に入れない（次サイクルで再挑戦させる）。
        """
        keys = [key for key in dict.fromkeys(sources) if key not in seen]
        if not keys:
            return 0
        try:
            result = ctx.memory_repo.delete_many(keys)
        except Exception:
            logger.warning("WikiWorker: failed to delete sources for %s", persona, exc_info=True)
            return 0
        if not isinstance(result, Success):
            # delete_many はチャンク単位で all-or-nothing。毒キー 1 件で全部戻ると、
            # ページは sources を書き終えているので毎サイクル同じ記憶が選ばれ本文が太る。
            # 1 件ずつ再試行し、なお失敗するキーは tombstone して inbox（active）から外す
            # （tombstoned は次サイクルの _purge_obsolete が拾う）。
            logger.warning("WikiWorker: batch delete failed, retrying per key: %s", result.error)
            deleted = 0
            for key in keys:
                one = ctx.memory_repo.delete_many([key])
                if isinstance(one, Success):
                    seen.add(key)
                    deleted += 1
                    continue
                ctx.memory_repo.tombstone(key)
                seen.add(key)
                logger.warning("WikiWorker: source %s could not be deleted; tombstoned", key)
            if deleted and self.vector_enabled:
                vector_index.drop_memories(self._settings, persona, [k for k in keys if k in seen])
            return deleted
        seen.update(keys)
        if self.vector_enabled:
            vector_index.drop_memories(self._settings, persona, keys)
        return int(result.value)

    def _repair_links(self, store: WikiStore) -> int:
        """dangling な wikilink をプレーンテキストにする（repoint は意味判断が要るので削除側に倒す）。"""
        repaired = 0
        for slug, targets in store.dangling_links().items():
            page_result = store.read_page(slug)
            if not isinstance(page_result, Success):
                continue
            page = page_result.value
            body = page.body
            for target in targets:
                body = body.replace(f"[[{target}]]", target)
            if body != page.body:
                store.write_page(
                    slug,
                    page.title,
                    body,
                    project=page.project,
                    sources=page.sources,
                    tags=page.tags,
                )
                repaired += 1
        return repaired

    def _most_recent(self, memories: list[Memory]) -> list[Memory]:
        return _by_recency(memories)[: self._cfg.max_memories_per_topic]

    # ------------------------------------------------------------------
    # 編纂
    # ------------------------------------------------------------------

    def _compile_persona(self, ctx, persona: str) -> None:
        from nous.domain.shared.time_utils import get_now
        from nous.infrastructure.wiki.store import WikiStore

        now = get_now(self._cfg.run_at_tz)
        store = WikiStore(self._settings.data_root, persona)
        # Zero Inbox: Wiki/日記が吸収済みの記憶を先に物理削除する（旧 archived の溜まり場を消す）。
        purged, purged_keys = self._purge_obsolete(ctx, persona)
        if purged:
            self._record_event(
                ctx,
                persona,
                f"purged {purged} obsolete memories",
                {"purged": purged, "keys": purged_keys[:_EVENT_KEY_SAMPLE]},
            )
        self._dedupe_open_questions(ctx, persona)
        all_result = ctx.memory_repo.find_all()
        memories: list[Memory] = list(all_result.value) if isinstance(all_result, Success) else []
        deleted_seen: set[str] = set()
        journal_sources = self._compile_journal(ctx, persona, store, now)
        questions: list[dict] = []
        topics = self._select_topics(memories, now, store, persona)
        if not topics:
            # 「起動して何もしなかった」と「壊れて何もできなかった」を後から区別する（#45）。
            # buckets も出す: memories があってもクラスタが小さければ topic 0 件になる。
            excluded = sum(
                1 for m in memories if m.lifecycle_status != "active" or getattr(m, "source_type", "") == "consolidated"
            )
            self._record_event(
                ctx,
                persona,
                f"skipped: no topic (memories={len(memories)}, excluded={excluded}, buckets=0)",
                {"memories": len(memories), "excluded": excluded, "buckets": 0},
            )
        for topic, selected in topics:
            try:
                questions.extend(self._compile_topic(ctx, persona, store, topic, selected, now, deleted_seen) or [])
            except Exception:
                logger.exception("WikiWorker: topic=%s failed", topic)
                self._record_event(ctx, persona, f"error: topic {topic} failed", None)
        # 自走調査（#40）: 編纂で出た問いを登録 MCP ツールで確かめ、本文に根拠を足す。
        self._resolve_questions(ctx, persona, store, questions)
        # 索引維持（§4.6-6）: 外部リンクの dangling をプレーンテキストに落とす。
        repaired = self._repair_links(store)
        if repaired:
            logger.info("WikiWorker: persona=%s repaired %d pages with dangling links", persona, repaired)
        # 日記が取り込んだ源記憶も物理削除する（ページが正本）。
        self._delete_sources(ctx, persona, journal_sources, deleted_seen)

    def _purge_obsolete(self, ctx, persona: str) -> tuple[int, list[str]]:
        """archived / tombstoned / consolidated（旧 gist）を cycle 冒頭で一括物理削除する。

        ``consolidated`` だけは**消す前に JSONL へ退避する**。gist は Wiki の topic 候補から
        除外されているので、Wiki 側に本文のコピーが無い（消したら二度と戻らない）。
        退避に失敗したら gist は消さない（fail-closed）。戻り値は (削除件数, 消したキー)。
        """
        try:
            found = ctx.memory_repo.find_obsolete()
        except Exception:
            logger.warning("WikiWorker: obsolete key lookup failed for %s", persona, exc_info=True)
            return 0, []
        if not isinstance(found, Success) or not found.value:
            return 0, []
        rows = found.value
        gist_keys = [r["key"] for r in rows if r.get("source_type") == "consolidated"]
        keys = [r["key"] for r in rows if r.get("source_type") != "consolidated"]
        if gist_keys:
            if self._dump_gists(ctx, persona, gist_keys):
                keys.extend(gist_keys)
            else:
                self._record_event(
                    ctx,
                    persona,
                    "warning: gist purge skipped (dump failed)",
                    {"keys": len(gist_keys)},
                )
        if not keys:
            return 0, []
        try:
            result = ctx.memory_repo.delete_many(keys)
        except Exception:
            logger.warning("WikiWorker: purge failed for %s", persona, exc_info=True)
            return 0, []
        if not isinstance(result, Success):
            logger.warning("WikiWorker: purge failed for %s: %s", persona, result.error)
            return 0, []
        if self.vector_enabled:
            vector_index.drop_memories(self._settings, persona, keys)
        logger.info("WikiWorker: persona=%s purged %d obsolete memories", persona, result.value)
        return int(result.value), keys

    def _dump_gists(self, ctx, persona: str, keys: list[str]) -> bool:
        """旧 gist の本文を ``<persona>/wiki/_purged/gists-YYYYMMDD.jsonl`` に退避する。

        失敗したら False を返し、呼び手は gist を消さない（不可逆な loss を防ぐ）。
        """
        from nous.domain.shared.time_utils import get_now
        from nous.infrastructure.wiki.store import WikiStore

        dumped = ctx.memory_repo.dump_rows(keys)
        if not isinstance(dumped, Success) or not dumped.value:
            logger.warning("WikiWorker: gist dump read failed for %s", persona)
            return False
        day = get_now(self._cfg.run_at_tz).strftime("%Y%m%d")
        path = WikiStore(self._settings.data_root, persona).root / _GIST_DUMP_SUBDIR / f"gists-{day}.jsonl"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                for row in dumped.value:
                    fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        except Exception:
            logger.warning("WikiWorker: gist dump write failed for %s", persona, exc_info=True)
            return False
        logger.info("WikiWorker: persona=%s dumped %d gists to %s", persona, len(dumped.value), path)
        return True

    # ------------------------------------------------------------------
    # 日記（前日 JST の記憶 → 1 ページ）
    # ------------------------------------------------------------------

    def _compile_topic(
        self,
        ctx,
        persona: str,
        store: WikiStore,
        topic: str,
        memories: list[Memory],
        now: datetime,
        seen: set[str],
    ) -> list[dict]:
        """1 topic 分を編纂する。戻り値は調査に回す問い（``topic`` を埋めたもの）。"""
        pages = store.list_pages()
        memories = self._topic_memories(memories)
        candidate_keys = [m.key for m in memories]  # 監査イベントの入力根拠
        payload, error, attempt = self._ask_and_parse(topic, memories, pages, now)
        if payload is None:
            self._record_event(
                ctx,
                persona,
                f"error: {error}",
                {
                    "topic": topic,
                    "attempt": attempt,
                    "input_count": len(memories),
                    "input_keys": candidate_keys[:_EVENT_KEY_SAMPLE],
                    **(self._last_llm or {}),
                },
            )
            return []
        page_dicts = payload["pages"]
        if not page_dicts:
            # 成功扱いで無言で抜けると「動いているのに更新されない」がログに残らない。
            self._record_event(
                ctx,
                persona,
                f"skipped: no pages returned for {topic}",
                {"topic": topic, "input_count": len(memories), "input_keys": candidate_keys[:_EVENT_KEY_SAMPLE]},
                event_type="wiki.compile",
            )
        elif attempt:
            # 再試行で救ったことを残す（「効いたのかモデルを替えるべきか」を後から判定する）。
            self._record_event(
                ctx,
                persona,
                f"recovered: {topic} on attempt {attempt + 1}",
                {
                    "topic": topic,
                    "attempt": attempt,
                    "input_count": len(memories),
                    "input_keys": candidate_keys[:_EVENT_KEY_SAMPLE],
                    **(self._last_llm or {}),
                },
                event_type="wiki.compile",
            )

        candidates = {m.key: m for m in memories}
        existing_slugs = {p.slug for p in pages}
        compiled = 0
        written_slugs: set[str] = set()
        deleted_slugs: set[str] = set()
        for page in page_dicts:
            try:
                if self._apply_page(ctx, persona, store, topic, page, candidates, existing_slugs, seen):
                    compiled += 1
                    written_slugs.add(str(page.get("slug")))
                    deleted_slugs.update(str(d) for d in page.get("delete", []) or [] if isinstance(d, str))
            except Exception as e:
                logger.warning("WikiWorker: page apply failed (%s): %s", page.get("slug"), e)
                self._record_event(
                    ctx,
                    persona,
                    f"error: page {page.get('slug')} failed: {e}",
                    {"topic": topic, "slug": page.get("slug")},
                )

        # 幻覚 slug ガードは「実際に書けた slug ∪ 既存から今サイクルで消したものを除いたもの」。
        # 目次と日記は矛盾の当事者にならないので外す。
        known = (existing_slugs - deleted_slugs) | written_slugs
        known_slugs = {s for s in known if s and s != INDEX_SLUG and not s.startswith(_JOURNAL_SLUG_PREFIX)}

        if self._cfg.conflict_check_enabled:
            self._apply_conflicts(
                ctx,
                persona,
                payload["conflicts"],
                payload["questions"],
                store=store,
                topic=topic,
                known_slugs=known_slugs,
            )

        logger.info("WikiWorker: persona=%s topic=%s compiled %d pages", persona, topic, compiled)
        return [
            {**item, "topic": str(item.get("topic") or topic)}
            for item in payload["questions"]
            if str(item.get("query") or "").strip()
        ]

    # ------------------------------------------------------------------
    # 自走調査（#40）— 登録済み MCP ツールだけを使う。無ければ何もしない
    # ------------------------------------------------------------------

    def _write_research(self, ctx, persona: str, store: WikiStore, found: dict[str, dict]) -> None:
        """slug ごとに 1 回だけ ``## 外部情報`` を追記する（ループ内で書かない）。"""
        for slug, entry in found.items():
            page: WikiPage = entry["page"]
            body = self._with_research_section(page, entry["hits"])
            if body == page.body:
                continue  # 同じ URL は二度書かない（ページの updated を無駄に進めない）
            written = store.write_page(
                slug, page.title, body, project=page.project, sources=page.sources, tags=page.tags
            )
            if isinstance(written, Failure):
                # 書込み失敗は編纂全体の失敗ではない（30 分後の再挑戦を誘発しない）。
                self._record_event(
                    ctx,
                    persona,
                    f"warning: research write {slug} failed: {written.error}",
                    {"slug": slug},
                    event_type="wiki.research",
                )
                continue
            if self.vector_enabled:
                vector_index.sync_page(self._settings, persona, slug, page.title, body)
            self._record_event(
                ctx,
                persona,
                f"updated {slug} with {len(entry['hits'])} external sources",
                {"slug": slug, "hits": [h["url"] for h in entry["hits"]]},
                event_type="wiki.research",
            )

    def _with_research_section(self, page: WikiPage, hits: list[dict]) -> str:
        """本文末尾に ``## 外部情報`` 節を足した本文（入らなければ本文のまま）。

        上限判定は frontmatter 込みで行う（``write_page`` と同じ物差し。本文だけで
        測ると必ず書込みに失敗するページを作る）。

        shortcut: 節は 1 つだけ（2 回目以降の調査結果は同じ節に足さない）。
        増やすなら URL 単位の差分追記に変える。
        """
        if "## 外部情報" in page.body:
            return page.body
        lines = [f"- [{h['title']}]({h['url']})" for h in hits if h.get("url")]
        if not lines:
            return page.body
        merged = page.body.rstrip() + "\n\n## 外部情報\n" + "\n".join(lines)
        # write_pageと同じ物差し（frontmatter 込みのレンダリング結果）で測る。
        size = len(render_page(replace(page, body=merged)).encode("utf-8"))
        if size > self._cfg.max_page_bytes:
            logger.warning(
                "WikiWorker: research section does not fit in %d bytes (needs %d)", self._cfg.max_page_bytes, size
            )
            return page.body
        return merged

    def _apply_page(
        self,
        ctx,
        persona: str,
        store: WikiStore,
        topic: str,
        page: dict,
        candidates: dict[str, Memory],
        existing_slugs: set[str],
        seen: set[str],
    ) -> bool:
        """1 ページ分を検証 → ファイル書込み → 索引更新 → 監査。適用したら True。"""
        slug = page.get("slug")
        title = page.get("title")
        body = page.get("body")
        if not isinstance(slug, str) or not isinstance(title, str) or not isinstance(body, str):
            raise ValueError("slug/title/body must be strings")
        if not slug.startswith(f"{topic}-") and slug != topic:
            # クラスタ外 slug は許可しない（topic ファイルの散逸防止）
            raise ValueError(f"slug {slug!r} does not belong to topic {topic!r}")
        if len(body.encode()) > self._cfg.max_page_bytes:
            raise ValueError(f"body too large for {slug}: {len(body.encode())} bytes")

        sources = [s for s in page.get("sources", []) if isinstance(s, str) and s in candidates]
        if not sources:
            raise ValueError(f"page {slug} has no valid sources")
        if len(sources) > self._cfg.max_sources_per_page:
            raise ValueError(f"page {slug} has too many sources ({len(sources)})")

        existing = store.read_page(slug)
        existed = isinstance(existing, Success)
        previous_hash = None
        if isinstance(existing, Success):
            previous_hash = _hash_of(existing.value.title, existing.value.body)
            # 源は減らさない。消えた記憶のキーは「そのページを支えた履歴」で、
            # 改訂で落とすと本文の根拠がどこからも読めなくなる。
            sources = list(dict.fromkeys([*sources, *existing.value.sources]))
            if len(sources) > self._cfg.max_sources_per_page:
                sources = sources[: self._cfg.max_sources_per_page]
        written = store.write_page(
            slug,
            title,
            body,
            project=_project_of(page, topic),
            sources=tuple(sources),
        )
        if isinstance(written, Failure):
            raise RuntimeError(f"write_page failed: {written.error}")
        # ページ本文がディスクに載ってから inbox を消す（先に消すと本文が失われる）。
        deleted = self._delete_sources(ctx, persona, sources, seen)
        if self.vector_enabled:
            vector_index.sync_page(self._settings, persona, slug, title, body)

        for doomed in page.get("delete", []) or []:
            if isinstance(doomed, str) and doomed in existing_slugs and doomed.startswith(f"{topic}-"):
                store.delete_page(doomed)
                if self.vector_enabled:
                    vector_index.drop_page(self._settings, persona, doomed)
                # 削除も監査に残す（「いつ何が消えたか」を後から追えるように）。
                self._record_event(
                    ctx,
                    persona,
                    f"deleted {doomed} (merged into {slug})",
                    {
                        "slug": doomed,
                        "reason": "merged",
                        "into": slug,
                        "topic": topic,
                        "source_count": len(sources),
                        "input_count": len(candidates),
                    },
                    event_type="wiki.deleted",
                )

        action = "updated" if existed else "created"
        new_hash = _hash_of(title, body)
        # 「なぜこの版になったか」を後から読めるように入力の根拠を残す。
        reason = "created" if not existed else "unchanged-body" if previous_hash == new_hash else "revised"
        self._record_event(
            ctx,
            persona,
            f"{action} {slug} from {len(sources)} memories",
            {
                "slug": slug,
                "action": action,
                "reason": reason,
                "topic": topic,
                "sources": sources,
                "source_count": len(sources),
                "input_count": len(candidates),
                "input_keys": list(candidates.keys())[:_EVENT_KEY_SAMPLE],
                "input_truncated": len(candidates) > _EVENT_KEY_SAMPLE,
                "unused_sources": [k for k in candidates if k not in sources][:_EVENT_KEY_SAMPLE],
                "deletes": page.get("delete", []),
                "deleted": deleted,
                "previous_hash": previous_hash,
                "page_hash": new_hash,
                "body_bytes": len(body.encode()),
            },
        )
        return True

    # ------------------------------------------------------------------
    # LLM（provider 解決 + テストフック）
    # ------------------------------------------------------------------

    _ask_llm_for_test: str | None = None
    _ask_llm_raise: Exception | None = None
    #: 矛盾判定の provider 差し替え（テスト用。未設定なら factory から作る）。
    _provider_for_test: object | None = None

    def _ask_and_parse(
        self, topic: str, memories: list[Memory], pages: list[WikiPage], now: datetime
    ) -> tuple[dict[str, list[dict]] | None, str, int]:
        """LLM 呼び出し + パース。空応答/切れ JSON は 1 回だけ予算を倍にして再試行。

        reasoning モデルは思考トークンも max_tokens を食うため、長い応答が途中で切れて
        JSON が閉じないことがある（2026-11-09 の本番障害: char 4153 で Unterminated）。
        成功時は (pages, "", 成功した attempt 番号)、失敗時は (None, 監査用メッセージ, 最後の attempt)。
        """
        error = ""
        for attempt in range(self._llm_attempts):
            raw = self._ask_llm(topic, memories, pages, now, boost=attempt)
            if raw is None:
                # collect_text は ErrorEvent で None、本文が無ければ "" を返す（区別できる）。
                error = f"llm stream error for {topic} (attempt {attempt + 1})"
            elif not raw:
                error = f"llm returned no text for {topic} (attempt {attempt + 1})"
            else:
                try:
                    return self._parse_response(raw), "", attempt
                except Exception as e:
                    error = f"invalid llm response for {topic}: {e} (attempt {attempt + 1})"
                    logger.warning("WikiWorker: %s", error)
            if attempt + 1 < self._llm_attempts:
                logger.warning("WikiWorker: retrying %s with a larger budget", topic)
            else:
                return None, error, attempt
        return None, error, self._llm_attempts - 1

    def _ask_llm(
        self, topic: str, memories: list[Memory], pages: list[WikiPage], now: datetime, boost: int = 0
    ) -> str | None:
        return self._ask_text(self._build_prompt(topic, memories, pages, now), boost)

    def _ask_text(self, prompt: str, boost: int = 0) -> str | None:
        """プロンプト 1 本を LLM に渡す（テストフックはここで受ける）。"""
        if self._ask_llm_raise is not None:
            raise self._ask_llm_raise
        if self._ask_llm_for_test is not None:
            return self._ask_llm_for_test

        cfg = self._cfg
        api_key = cfg.get_effective_api_key(self._settings)
        if not api_key:
            raise RuntimeError("wiki LLM api_key is not configured")

        from nous.infrastructure.llm.base import LLMMessage
        from nous.infrastructure.llm.factory import get_provider
        from nous.infrastructure.llm.text_utils import collect_text

        provider: LLMProvider = get_provider(cfg.provider, api_key, cfg.model, cfg.base_url)
        max_tokens = self._max_tokens * (2**boost)
        text = asyncio.run(
            collect_text(
                provider,
                messages=[LLMMessage(role="user", content=prompt)],
                system="",
                tools=None,
                temperature=0.0,
                max_tokens=max_tokens,
            )
        )
        # 監査用の計器（attempt / 実際の予算 / 返ってきた本文長 / stream エラーか）。
        self._last_llm = {
            "max_tokens": max_tokens,
            "text_len": len(text or ""),
            "stream_error": text is None,
        }
        return text

    def _topic_memories(self, memories: list[Memory]) -> list[Memory]:
        return _by_recency(memories)[: self._cfg.max_memories_per_topic]

    def _build_prompt(self, topic: str, memories: list[Memory], pages: list[WikiPage], now: datetime) -> str:
        page_lines = [
            json.dumps(
                {
                    "slug": p.slug,
                    "title": p.title,
                    "project": p.project,
                    "updated": p.updated,
                    "days_since_update": _days_since(p.updated, now),
                    "sources": list(p.sources),
                    **({"body": p.body} if _topic_of_page(p) == topic else {"preview": p.body[:_PAGE_PREVIEW_CHARS]}),
                },
                ensure_ascii=False,
            )
            for p in pages
            if p.slug != "index" and not p.slug.startswith(_JOURNAL_SLUG_PREFIX)
        ]
        memory_lines = [
            json.dumps(
                {
                    "key": m.key,
                    "when": _day_of(m),
                    "kind": getattr(m, "kind", "semantic"),
                    "importance": round(float(m.importance), 2),
                    "content": m.content[:_CONTENT_PREVIEW_CHARS],
                },
                ensure_ascii=False,
            )
            for m in memories
        ]
        return _WIKI_PROMPT.format(
            now=now.isoformat(),
            topic=topic,
            slug_prefix=f"{topic}-",
            max_bytes=self._cfg.max_page_bytes,
            stale_days=self._cfg.stale_days,
            conflict_instructions=_CONFLICT_ON if self._cfg.conflict_check_enabled else _CONFLICT_OFF,
            pages="\n".join(page_lines) or "(なし)",
            memories="\n".join(memory_lines),
        )

    def _parse_response(self, text: str) -> dict[str, list[dict]]:
        """LLM 応答 → ``{"pages": [...], "conflicts": [...], "questions": [...]}``。

        コードフェンス・前後説明文は ``_parse_json_object`` が吸収する。呼び出し側
        （_compile_topic）が ValueError/JSONDecodeError を捕捉して監査に error 行を
        書きファイルを変えない契約。ここで握り潰さない。

        ``conflicts`` / ``questions`` は後方互換のため欠落を空リストとして扱う（§3.3）。
        """
        data = _parse_json_object(text)
        pages = data.get("pages")
        if not isinstance(pages, list):
            raise ValueError("missing 'pages' array")
        return {
            "pages": [p for p in pages if isinstance(p, dict)],
            "conflicts": [c for c in data.get("conflicts") or [] if isinstance(c, dict)],
            "questions": [q for q in data.get("questions") or [] if isinstance(q, dict)],
        }

    # ------------------------------------------------------------------
    # session_events 監査
    # ------------------------------------------------------------------

    def _record_event(
        self, ctx, persona: str, summary: str, detail: dict | None, *, event_type: str = "wiki.compiled"
    ) -> None:
        if summary.startswith("error:"):
            self._cycle_errors += 1
        try:
            from nous.domain.memory.session_event import SessionEvent
            from nous.domain.shared.time_utils import get_now
            from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

            SessionEventRepository(ctx.connection).insert(
                SessionEvent(
                    session_id="wiki_worker",
                    persona=persona,
                    event_type=event_type,
                    timestamp=get_now(),
                    summary=summary[:200],
                    detail=json.dumps(detail, ensure_ascii=False) if detail else None,
                    metadata=None,
                )
            )
        except Exception:
            logger.exception("WikiWorker: failed to record event")


def _local_day(ts: datetime, tz: tzinfo | None) -> date:
    """datetime を ``tz`` の日付にする（naive は tz 付きとみなす）。"""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=tz)
    if tz is None:
        return ts.date()
    return ts.astimezone(tz).date()


def _by_recency(memories: list[Memory]) -> list[Memory]:
    """新しい順（``updated_at`` 優先、無ければ ``created_at``）。"""

    def _ts(m: Memory):
        return getattr(m, "updated_at", None) or m.created_at

    return sorted(memories, key=_ts, reverse=True)


def _days_since(page_updated: str | None, now: datetime) -> int | None:
    """``updated`` からの経過日数（パース不能なら None）。放置ページを名指しするため。"""
    if not page_updated:
        return None
    try:
        stamp = datetime.fromisoformat(page_updated.replace("Z", "+00:00"))
    except ValueError:
        return None
    try:
        return max(0, (now - stamp).days)
    except TypeError:
        return None


def _day_of(memory: Memory) -> str:
    """記憶が書かれた日（``YYYY-MM-DD``）。LLM に新旧を判断させるための最小のヒント。"""
    stamp = getattr(memory, "updated_at", None) or memory.created_at
    if isinstance(stamp, datetime):
        return stamp.strftime("%Y-%m-%d")
    if isinstance(stamp, str) and len(stamp) >= 10:
        return stamp[:10]
    return ""


def _topic_of(memory: Memory) -> str:
    """記憶 → クラスタ slug（project:* タグ優先、無ければ persona の固定 slug）。"""
    tags = getattr(memory, "tags", None) or []
    for tag in tags:
        if isinstance(tag, str) and tag.startswith("project:"):
            slug = tag.split(":", 1)[1]
            slug = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-")
            if slug:
                return f"project-{slug}"
    return "persona"


def _topic_of_page(page: WikiPage) -> str:
    """wiki ページ → クラスタ slug（``_topic_of`` と同じ写像）。"""
    return f"project-{page.project}" if page.project else "persona"


def _project_of(page: dict, topic: str) -> str | None:
    """ページの project 値（topic が project-<slug> なら slug を返す）。"""
    value = page.get("project")
    if isinstance(value, str) and value:
        return value
    if topic.startswith("project-"):
        return topic[len("project-") :]
    return None
