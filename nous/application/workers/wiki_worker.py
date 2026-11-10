"""WikiWorker — ドリーミング（wiki 編纂）worker。

計画書: ``docs/superpowers/plans/2026-11-07-wiki-dreaming.md`` §4.2。

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
import hashlib
import json
import re
import threading
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING

from nous.application.wiki import vector_index
from nous.application.wiki.research import research
from nous.domain.shared.result import Failure, Success
from nous.domain.value_objects import normalize_emotion, normalize_importance
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.wiki.store import INDEX_SLUG, render_page

if TYPE_CHECKING:
    from nous.config.settings import Settings, WikiConfig
    from nous.domain.memory.entities import Memory
    from nous.infrastructure.llm.base import LLMProvider
    from nous.infrastructure.wiki.store import WikiPage, WikiStore

logger = get_logger(__name__)

#: 編纂対象クラスタの最小記憶数（これ未満の topic はページ化しない）。
MIN_TOPIC_MEMORIES = 3
#: wiki 側の時刻は秒精度なので、秒未満の差は stale と見なさない。
_STALE_SLACK = timedelta(seconds=2)

#: 日記ページの slug 接頭辞（``journal-YYYY-MM-DD``）。topic 編纂の巡回対象外。
_JOURNAL_SLUG_PREFIX = "journal-"

#: LLM に渡す記憶本文の切り詰め長。
_CONTENT_PREVIEW_CHARS = 300

#: 既存ページ目次で LLM に渡す本文プレビュー長。
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


_JOURNAL_PROMPT = """あなたは日記を書く記録係です。{day} の記憶だけを材料に、その日の記録を Markdown で書いてください。

現在時刻: {now}

書き方:
- 見出しは必ず次の 5 つだけを、この順・この表記で使う:
  ## やったこと
  ## 感想
  ## 決めたこと
  ## 引っかかったこと
  ## 未解決
- ## 感想 は「その日に起きたことに対して何を感じたか・どう思ったか」を本人の口調で書く。事実の列挙にはしない。
- 材料に無い事実は書かない（推測・脚色・一般論での補完は禁止）。材料が無い見出しは省略してよい。
- {length_hint}
- 既存ページへは [[slug]] 形式でリンクしてよい（存在しない slug はプレーンテキストに落ちる）:
{pages}
- 本文は {max_bytes} バイト以内。

材料（{day} の記憶）:
{memories}

JSON ではなく Markdown 本文だけを返してください（説明文は不要）。
"""

_STATE_PROMPT = """以下はある人物の今日の日記とその材料です。この日の出来事を経て、いまの感情・体調・精神状態を推定してください。

日記:
{body}

材料:
{memories}

以下の JSON のみを返してください（説明文は不要。推定できない項目は省略）:
{{"emotion": "喜/怒/哀/楽 などの一語", "emotion_intensity": 0.0〜1.0, "physical_state": "体の状態の短文", "mental_state": "精神状態の短文", "body_state": {{"fatigue": 0.0〜1.0}}}}
"""


class WikiWorker:
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

        優先度: source 腐敗/更新のある topic（§4.6 腐敗検出）→ 記憶数降順。
        """
        buckets: dict[str, list[Memory]] = {}
        for m in memories:
            if m.lifecycle_status != "active":
                continue
            if getattr(m, "source_type", "") == "consolidated":
                continue
            buckets.setdefault(_topic_of(m), []).append(m)

        stale = self._stale_topics(store, memories, persona)
        last_compiled = self._last_compiled(store)
        # 既にページのある topic は新着 1 件でも巡回対象にする。源を archive すると
        # active が減り、MIN_TOPIC_MEMORIES の下限でその topic が永久に選ばれなくなるため。
        topics = [
            (slug, mems)
            for slug, mems in buckets.items()
            if len(mems) >= (1 if slug in last_compiled else MIN_TOPIC_MEMORIES)
        ]
        # 並び順: stale 先頭 → 最後に編纂された時刻が古い順（未編纂は "" で最優先）
        # → 同順位は記憶数降順。これで小クラスタにも巡回が回る。
        topics.sort(key=lambda item: (item[0] not in stale, last_compiled.get(item[0], ""), -len(item[1])))
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

    def _stale_topics(self, store: WikiStore, memories: list[Memory], persona: str) -> set[str]:
        """source が消滅・tombstoned・またはページより新しい topic を返す。

        archived は「意図的に沈めた」状態（decay の忘却 / wiki への吸収）なので stale にしない。
        ここで stale にすると毎サイクル同じ topic を編纂し続ける（無限再編纂）。
        """
        by_key = {m.key: m for m in memories}
        stale: set[str] = set()
        for page in store.list_pages():
            if page.slug.startswith(_JOURNAL_SLUG_PREFIX) or not page.sources:
                continue
            topic = _topic_of_page(page)
            for key in page.sources:
                memory = by_key.get(key)
                if memory is None or memory.lifecycle_status == "tombstoned":
                    stale.add(topic)
                    break
                if memory.lifecycle_status != "active":
                    continue
                if _page_is_behind(page.updated, getattr(memory, "updated_at", None) or memory.created_at):
                    stale.add(topic)
                    break
        return stale

    def _archive_sources(self, ctx, sources: list[str], seen: set[str]) -> int:
        """編纂済みの源記憶を archived へ沈める（decay と同じ lifecycle 遷移）。

        削除はしない: ``page.sources`` は memory key を参照し続けるので、消すと腐敗検出が壊れる。
        archived は既定の検索対象外（SearchQuery.lifecycle_status="active"）なので、
        検索面からは実質消える。tombstone は行わない（不可逆なのは decay 側の領分）。
        ``sources`` は active な記憶からのみ選ばれる（SELECT 段で除外済み）ので、
        戻り値はそのまま「active → archived に遷移した数」になる。ただし同じ key を
        複数ページが引用しうるので、``seen`` で cycle 内の二重計上を防ぐ。
        """
        if not self._cfg.archive_sources:
            return 0
        archived = 0
        for key in sources:
            if key in seen:
                continue
            try:
                result = ctx.memory_repo.update(key, lifecycle_status="archived")
            except Exception:
                logger.warning("WikiWorker: failed to archive source %s", key, exc_info=True)
                continue
            if isinstance(result, Success):
                seen.add(key)
                archived += 1
        return archived

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
        def _ts(m: Memory):
            return getattr(m, "updated_at", None) or m.created_at

        return sorted(memories, key=_ts, reverse=True)[: self._cfg.max_memories_per_topic]

    # ------------------------------------------------------------------
    # 編纂
    # ------------------------------------------------------------------

    def _compile_persona(self, ctx, persona: str) -> None:
        from nous.domain.shared.time_utils import get_now
        from nous.infrastructure.wiki.store import WikiStore

        now = get_now(self._cfg.run_at_tz)
        store = WikiStore(self._settings.data_root, persona)
        all_result = ctx.memory_repo.find_all()
        memories: list[Memory] = list(all_result.value) if isinstance(all_result, Success) else []
        archived_seen: set[str] = set()
        self._compile_journal(ctx, persona, store, now)
        questions: list[dict] = []
        for topic, selected in self._select_topics(memories, now, store, persona):
            try:
                questions.extend(self._compile_topic(ctx, persona, store, topic, selected, now, archived_seen) or [])
            except Exception:
                logger.exception("WikiWorker: topic=%s failed", topic)
                self._record_event(ctx, persona, f"error: topic {topic} failed", None)
        # 自走調査（#40）: 編纂で出た問いを登録 MCP ツールで確かめ、本文に根拠を足す。
        self._resolve_questions(ctx, persona, store, questions)
        # 索引維持（§4.6-6）: 外部リンクの dangling をプレーンテキストに落とす。
        repaired = self._repair_links(store)
        if repaired:
            logger.info("WikiWorker: persona=%s repaired %d pages with dangling links", persona, repaired)
        # 記憶層の矛盾掃除（#39）: 週 1 回だけ。候補抽出は LLM 0 回、判定は上限付き。
        self._sweep_memory_conflicts(ctx, persona, memories, now)

    # ------------------------------------------------------------------
    # 日記（前日 JST の記憶 → 1 ページ）
    # ------------------------------------------------------------------

    def _compile_journal(self, ctx, persona: str, store: WikiStore, now: datetime) -> None:
        """前日（JST）の記憶を 1 ページの日記にまとめる。0 件なら何もしない。

        同じ日に 2 回走っても ``journal-YYYY-MM-DD`` の上書きで 1 ページのまま。
        失敗は監査に残してサイクルは続ける（日記は編纂の前提条件ではない）。
        """
        if not self._cfg.journal_enabled:
            return
        day = (now - timedelta(days=1)).date()
        try:
            memories = self._journal_memories(ctx, day, now)
            if not memories:
                return
            slug = f"{_JOURNAL_SLUG_PREFIX}{day.isoformat()}"
            title = f"{day.isoformat()} の記録"
            existed = store.read_page(slug).is_ok
            # sources は候補（その日の記憶）からだけ作る。LLM に選ばせない。
            sources = tuple(m.key for m in memories)
            tag = day.strftime("%Y-%m")
            # 本文予算は「frontmatter を引いた残り」。write_page は frontmatter 込みで
            # max_page_bytes を見るので、sources が多い日は本文を減らさないと必ず落ちる。
            budget = self._cfg.max_page_bytes - _frontmatter_bytes(slug, title, sources, tag)
            raw = self._ask_text(self._build_journal_prompt(day, memories, store.list_pages(), now, max_bytes=budget))
            body = _strip_code_fence(raw or "")
            if not body:
                raise ValueError("llm returned no journal body")
            written = store.write_page(slug, title, body, sources=sources, tags=("journal", tag))
            if isinstance(written, Failure):
                raise RuntimeError(f"write_page failed: {written.error}")
            if self.vector_enabled:
                vector_index.sync_page(self._settings, persona, slug, title, body)
            action = "updated" if existed else "created"
            self._record_event(
                ctx,
                persona,
                f"{action} {slug} from {len(sources)} memories",
                {
                    "slug": slug,
                    "action": action,
                    "day": day.isoformat(),
                    "sources": list(sources),
                    "page_hash": _hash_of(title, body),
                    **(self._last_llm or {}),
                },
            )
            self._apply_journal_state(ctx, persona, slug, memories, body)
        except Exception as e:
            logger.warning("WikiWorker: journal %s failed: %s", day, e)
            self._record_event(ctx, persona, f"error: journal {day}: {e}", None)

    def _apply_journal_state(self, ctx, persona: str, slug: str, memories: list[Memory], body: str) -> None:
        """日記から感情・体調を 1 回だけ推定して persona 状態へ反映する。

        値が取れない（JSON でない・空）なら何もしない。失敗は 1 行残して続行（日記自体は正）。
        """
        if not self._cfg.journal_apply_state:
            return
        service = getattr(ctx, "persona_service", None)
        if service is None:
            self._record_event(ctx, persona, "skipped: journal state (no persona_service)", {"slug": slug})
            return
        try:
            raw = self._ask_text(self._build_state_prompt(memories, body)) or ""
            try:
                state = _parse_json_object(raw)
            except ValueError:
                logger.warning("WikiWorker: journal state is not JSON (%s)", slug)
                return

            applied: dict[str, object] = {}
            emotion = state.get("emotion")
            intensity = state.get("emotion_intensity")
            if isinstance(emotion, str) and emotion and isinstance(intensity, (int, float)):
                result = service.update_emotion(persona, emotion, float(intensity), context=f"journal:{slug}")
                if isinstance(result, Failure):
                    raise RuntimeError(f"update_emotion failed: {result.error}")
                # 保存された値を残す（正規化・クランプ後に何が入ったかが監査の事実）。
                applied["emotion"] = normalize_emotion(emotion)
                applied["emotion_intensity"] = normalize_importance(float(intensity))

            physical = state.get("physical_state")
            mental = state.get("mental_state")
            body_state = state.get("body_state")
            states: dict[str, object] = {}
            if isinstance(physical, str) and physical:
                states["physical_state"] = physical
            if isinstance(mental, str) and mental:
                states["mental_state"] = mental
            if isinstance(body_state, dict) and isinstance(body_state.get("fatigue"), (int, float)):
                states["fatigue"] = float(body_state["fatigue"])
            if states:
                result = service.update_physical_state(persona, **states)
                if isinstance(result, Failure):
                    raise RuntimeError(f"update_physical_state failed: {result.error}")
                applied.update(states)

            if not applied:
                return
            self._record_event(
                ctx,
                persona,
                f"applied state emotion={applied.get('emotion', '-')}"
                f" intensity={applied.get('emotion_intensity', '-')}",
                {"slug": slug, **applied},
            )
        except Exception as e:
            # "error:" を付けると cycle 失敗として数えられ 30 分後の再挑戦を誘発する。
            # 日記本体は書けているので、状態反映の失敗は warning 扱いにする。
            logger.warning("WikiWorker: journal state %s failed: %s", slug, e)
            self._record_event(ctx, persona, f"warning: journal state {slug}: {e}", None)

    def _build_state_prompt(self, memories: list[Memory], body: str) -> str:
        material = "\n".join(m.content[:_CONTENT_PREVIEW_CHARS] for m in memories)
        return _STATE_PROMPT.format(body=body, memories=material)

    def _journal_memories(self, ctx, day: date, now: datetime) -> list[Memory]:
        """``day``（JST）に作られた記憶を created_at 昇順で最大 journal_max_sources 件。

        archived も拾う。同日 2 回目のサイクルでは 1 回目が sources を archived に沈めて
        いるので、active に絞ると再実行のたびに痩せた日記で上書きしてしまう。
        """
        result = ctx.memory_repo.find_all()
        memories: list[Memory] = list(result.value) if isinstance(result, Success) else []
        tz = now.tzinfo
        picked = [m for m in memories if m.lifecycle_status != "tombstoned" and _local_day(m.created_at, tz) == day]
        picked.sort(key=lambda m: m.created_at)
        return picked[: self._cfg.journal_max_sources]

    def _build_journal_prompt(
        self,
        day: date,
        memories: list[Memory],
        pages: list[WikiPage],
        now: datetime,
        *,
        max_bytes: int | None = None,
    ) -> str:
        page_lines = [
            json.dumps({"slug": p.slug, "title": p.title}, ensure_ascii=False)
            for p in pages
            if p.slug != "index" and not p.slug.startswith(_JOURNAL_SLUG_PREFIX)
        ]
        memory_lines = [
            json.dumps(
                {
                    "key": m.key,
                    "created_at": m.created_at.isoformat(),
                    "content": m.content[:_CONTENT_PREVIEW_CHARS],
                },
                ensure_ascii=False,
            )
            for m in memories
        ]
        length_hint = (
            "材料が 5 件未満なので短く書く（各見出し 1〜3 行、水増し禁止）"
            if len(memories) < 5
            else "材料が多い日は列挙せず、要点を統合して書く"
        )
        return _JOURNAL_PROMPT.format(
            day=day.isoformat(),
            now=now.isoformat(),
            length_hint=length_hint,
            max_bytes=self._cfg.max_page_bytes if max_bytes is None else max_bytes,
            pages="\n".join(page_lines) or "(なし)",
            memories="\n".join(memory_lines),
        )

    def _compile_topic(
        self,
        ctx,
        persona: str,
        store: WikiStore,
        topic: str,
        memories: list[Memory],
        now: datetime,
        archived_seen: set[str],
    ) -> list[dict]:
        """1 topic 分を編纂する。戻り値は調査に回す問い（``topic`` を埋めたもの）。"""
        pages = store.list_pages()
        payload, error, attempt = self._ask_and_parse(topic, memories, pages, now)
        if payload is None:
            self._record_event(
                ctx,
                persona,
                f"error: {error}",
                {"topic": topic, "attempt": attempt, **(self._last_llm or {})},
            )
            return []
        page_dicts = payload["pages"]
        if not page_dicts:
            # 成功扱いで無言で抜けると「動いているのに更新されない」がログに残らない。
            self._record_event(ctx, persona, f"skipped: no pages returned for {topic}", {"topic": topic})
        elif attempt:
            # 再試行で救ったことを残す（「効いたのかモデルを替えるべきか」を後から判定する）。
            self._record_event(
                ctx,
                persona,
                f"recovered: {topic} on attempt {attempt + 1}",
                {"topic": topic, "attempt": attempt, **(self._last_llm or {})},
            )

        candidates = {m.key: m for m in memories}
        existing_slugs = {p.slug for p in pages}
        compiled = 0
        written_slugs: set[str] = set()
        deleted_slugs: set[str] = set()
        for page in page_dicts:
            try:
                if self._apply_page(ctx, persona, store, topic, page, candidates, existing_slugs, archived_seen):
                    compiled += 1
                    written_slugs.add(str(page.get("slug")))
                    deleted_slugs.update(str(d) for d in page.get("delete", []) or [] if isinstance(d, str))
            except Exception as e:
                logger.warning("WikiWorker: page apply failed (%s): %s", page.get("slug"), e)
                self._record_event(ctx, persona, f"error: page {page.get('slug')} failed: {e}", None)

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
                    "hits": [h["url"] for h in result["hits"]],
                    "answer": result["answer"][:1000],
                },
                event_type="wiki.research",
            )
        if no_tools:
            self._record_event(
                ctx, persona, "skipped: no mcp tool", {"questions": len(questions)}, event_type="wiki.research"
            )
        self._write_research(ctx, persona, store, found)

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
        archived_seen: set[str],
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

        existed = existing.is_ok
        written = store.write_page(
            slug,
            title,
            body,
            project=_project_of(page, topic),
            sources=tuple(sources),
        )
        if isinstance(written, Failure):
            raise RuntimeError(f"write_page failed: {written.error}")
        archived = self._archive_sources(ctx, sources, archived_seen)
        if self.vector_enabled:
            vector_index.sync_page(self._settings, persona, slug, title, body)

        for doomed in page.get("delete", []) or []:
            if isinstance(doomed, str) and doomed in existing_slugs and doomed.startswith(f"{topic}-"):
                store.delete_page(doomed)
                if self.vector_enabled:
                    vector_index.drop_page(self._settings, persona, doomed)

        action = "updated" if existed else "created"
        self._record_event(
            ctx,
            persona,
            f"{action} {slug} from {len(sources)} memories",
            {
                "slug": slug,
                "action": action,
                "topic": topic,
                "sources": sources,
                "deletes": page.get("delete", []),
                "archived": archived,
                "page_hash": _hash_of(title, body),
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

    # ------------------------------------------------------------------
    # 矛盾整理（#39）— wiki 層は編纂応答の conflicts、記憶層は週次掃除
    # ------------------------------------------------------------------

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
                )

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

    def _record_open_question(
        self, ctx, persona: str, question: str, *, topic: str, project: str | None = None
    ) -> None:
        """未解決の問いを記憶に 1 件置く（本文ハッシュで重複を抑止）。

        失敗を無言で潰さない: ``create_memory`` は意味的重複（>=0.75）で
        ``DuplicateMemoryError`` を返すので、監査に理由を残す。
        """
        digest = hashlib.sha256(question.encode("utf-8")).hexdigest()[:16]
        try:
            for memory in self._open_questions(ctx):
                if getattr(memory, "source_context", "") == f"open-question:{digest}":
                    return  # 同じ問いは一度だけ（毎サイクル増やさない）
        except Exception:
            logger.debug("WikiWorker: open-question dedupe lookup failed", exc_info=True)

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
                    source_context=f"open-question:{digest}",
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
            {"topic": topic, "project": project, "digest": digest},
            event_type="wiki.conflict",
        )

    @staticmethod
    def _open_questions(ctx) -> list:
        from nous.domain.shared.result import Success

        result = ctx.memory_repo.find_all()
        if not isinstance(result, Success):
            return []
        return [
            m
            for m in result.value
            if "open-question" in (getattr(m, "tags", ()) or ())
            and str(getattr(m, "source_context", "")).startswith("open-question:")
        ]

    def _last_sweep_at(self, ctx, persona: str) -> datetime | None:
        """直近の**成功した**記憶層掃除の時刻（session_events から取る）。

        ``error:`` / ``warning:`` 行は掃除済みと数えない（1 回の失敗で 168 時間ゲートが
        閉じて週次掃除が丸ごと飛ぶのを防ぐ）。
        """
        try:
            from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

            events = SessionEventRepository(ctx.connection).get_by_persona(
                persona, event_type="wiki.conflict_sweep", limit=10
            )
        except Exception:
            return None
        for event in events or ():
            summary = str(getattr(event, "summary", "") or "")
            if summary.startswith(("error:", "warning:")):
                continue
            ts = event.timestamp
            return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
        return None

    def _sweep_memory_conflicts(self, ctx, persona: str, memories: list[Memory], now: datetime) -> None:
        """記憶層の矛盾掃除（週 1 回）。候補抽出は LLM 0 回、判定は上限付き。"""
        cfg = self._cfg
        if not cfg.conflict_sweep_enabled:
            return
        last = self._last_sweep_at(ctx, persona)
        if last is not None and (now - last) < timedelta(hours=cfg.memory_conflict_interval_hours):
            return

        from nous.application.wiki.conflict_sweep import find_candidate_pairs, sweep

        pairs = find_candidate_pairs(
            memories, min_jaccard=cfg.memory_conflict_min_jaccard, limit=cfg.memory_conflict_max_pairs * 5
        )
        if not pairs:
            self._record_event(
                ctx, persona, "conflict sweep: no candidates", {"candidates": 0}, event_type="wiki.conflict_sweep"
            )
            return

        api_key = cfg.get_effective_api_key(self._settings)
        if not api_key and self._provider_for_test is None:
            self._record_event(
                ctx,
                persona,
                "skipped: conflict sweep has no api_key",
                {"candidates": len(pairs)},
                event_type="wiki.conflict_sweep",
            )
            return

        from nous.infrastructure.llm.factory import get_provider

        try:
            provider = self._provider_for_test or get_provider(cfg.provider, api_key, cfg.model, cfg.base_url)
            stats = asyncio.run(
                sweep(
                    pairs,
                    provider=provider,
                    close=lambda old_key, new_key: self._close_contradicted(ctx, old_key, new_key),
                    max_pairs=cfg.memory_conflict_max_pairs,
                )
            )
        except Exception as e:
            # ``error:`` を付けると cycle 失敗として数えられ 30 分後の再挑戦を誘発する
            # （編纂本体の失敗とは別物）。掃除の失敗は warning に留める。
            logger.warning("WikiWorker: conflict sweep failed: %s", e)
            self._record_event(
                ctx,
                persona,
                f"warning: conflict sweep failed: {e}",
                {"candidates": len(pairs)},
                event_type="wiki.conflict_sweep",
            )
            return
        # 全件失敗（判定不能＋ close 失敗）なら成功を名乗らない（数字が成功に見えると
        # 168h ゲートが閉じ、実質 0 件のまま 1 週間止まる）。
        all_failed = bool(stats["checked"]) and stats["failed"] >= stats["checked"]
        prefix = "warning: " if all_failed else ""
        self._record_event(
            ctx,
            persona,
            f"{prefix}conflict sweep: checked {stats['checked']} failed {stats['failed']} closed {stats['closed']}",
            stats,
            event_type="wiki.conflict_sweep",
        )

    def _close_contradicted(self, ctx, old_key: str, new_key: str) -> None:
        """古い記憶の validity window を閉じ、新しい記憶へ鎖で繋ぐ（削除はしない）。

        失敗は握り潰さずに投げる（``sweep`` が closed 件数を数えているので、
        ここで黙ると監査の数字が嘘になる）。
        """
        from nous.domain.shared.time_utils import get_now

        repo = ctx.memory_repo
        new_result = repo.find_by_key(new_key)
        valid_until = None
        if getattr(new_result, "is_ok", False) and new_result.value is not None:
            valid_until = getattr(new_result.value, "valid_from", None)
        result = repo.update_validity_window(
            memory_key=old_key, valid_until=valid_until or get_now(), superseded_by=new_key
        )
        if isinstance(result, Failure):
            raise RuntimeError(f"update_validity_window failed for {old_key}: {result.error}")

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

    def _build_prompt(self, topic: str, memories: list[Memory], pages: list[WikiPage], now: datetime) -> str:
        page_lines = [
            json.dumps(
                {
                    "slug": p.slug,
                    "title": p.title,
                    "project": p.project,
                    "sources": list(p.sources),
                    "preview": p.body[:_PAGE_PREVIEW_CHARS],
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


def _parse_json_object(text: str) -> dict:
    """LLM 応答から最初の JSON オブジェクトを取り出す（コードフェンス・前後説明文を許容）。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:]
    start, end = stripped.find("{"), stripped.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found in response")
    data = json.loads(stripped[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("response is not a JSON object")
    return data


def _strip_code_fence(text: str) -> str:
    """LLM 本文のコードフェンス（markdown の 3 連バックティック）を剥がす。

    閉じフェンスより後ろ（説明文など）は捨てる。閉じフェンスが無ければ全部本文。
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()[1:]
    for i, line in enumerate(lines):
        if line.strip() == "```":
            lines = lines[:i]
            break
    return "\n".join(lines).strip()


def _frontmatter_bytes(slug: str, title: str, sources: tuple[str, ...], tag: str) -> int:
    """frontmatter の実測バイト数（本文予算 = max_page_bytes - これ）。"""
    from nous.infrastructure.wiki.store import WikiPage, render_page

    page = WikiPage(
        slug=slug,
        title=title,
        body="",
        project=None,
        sources=tuple(sources),
        tags=("journal", tag),
        updated="",
        links=(),
    )
    return len(render_page(page).encode("utf-8"))


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


def _page_is_behind(page_updated: str | None, memory_updated: object) -> bool:
    """ページの更新時刻が記憶より古いか（パース不能なら False = 触らない）。

    wiki 側の時刻は秒精度で切り捨てて保存するので、秒未満の差は無視する（slack 2 秒）。
    これを入れないと「同じ秒に書いた記憶」で毎サイクル stale 扱いになる。
    """
    if not page_updated or memory_updated is None:
        return False
    try:
        page_ts = datetime.fromisoformat(page_updated.replace("Z", "+00:00"))
    except ValueError:
        return False
    if isinstance(memory_updated, str):
        try:
            memory_ts = datetime.fromisoformat(memory_updated.replace("Z", "+00:00"))
        except ValueError:
            return False
    elif isinstance(memory_updated, datetime):
        memory_ts = memory_updated
    else:
        return False
    if page_ts.tzinfo is None or memory_ts.tzinfo is None:
        page_ts = page_ts.replace(tzinfo=None)
        memory_ts = memory_ts.replace(tzinfo=None)
    return page_ts < memory_ts - _STALE_SLACK


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


def _hash_of(title: str, body: str) -> str:
    from nous.infrastructure.wiki.store import page_hash

    return page_hash(title, body)
