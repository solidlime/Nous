"""FreshnessWorker — LLM 鮮度評価 worker。

FSRS 機械 decay（DecayWorker）を代替せず、「時間経過でまだ有効か／古くなったか」を
LLM に評価させ、``lifecycle_status`` / ``valid_until`` / ``importance`` のみを更新する
（計画書 §5: 2026-11-07-active-memory-pi-hook-and-llm-freshness.md）。

- SELECT: lifecycle_status=active のうち (a) 7日以内に期限切れを迎える記憶、
  (b) 無期限 prospective（stale_days 以上未更新）、(c) stale_days 以上未アクセス記憶。
  gist（consolidated 派生）と source_type=consolidated は対象外（DecayWorker と同一規約）。
- 評価: 1 cycle を 1 回の batch prompt で LLM に渡し、verdict JSON を受ける。
  keep / expire / reschedule / demote の 4 種。
- 適用: update_memory で lifecycle_status / valid_until / importance のみ更新。
  importance >= 0.8 は protected — demote は適用しない（valid_until 系のみ可）。
- 監査: verdict 適用の有無にかかわらず、記憶毎に session_events へ 1 行
  (event_type="freshness.verdict") を記録。LLM 失敗は error 行として記録し、
  memory への書込みは行わない（fail-safe: 判断できないものは変えない）。
"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import timedelta
from typing import TYPE_CHECKING

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from nous.config.settings import FreshnessConfig, Settings
    from nous.domain.memory.entities import Memory
    from nous.infrastructure.llm.base import LLMProvider

logger = get_logger(__name__)

# 評価対象の記憶本文の切り詰め長（batch prompt の肥大化防止）
_CONTENT_PREVIEW_CHARS = 200

_FRESHNESS_PROMPT = """以下の記憶リストを評価し、各記憶が「現在も有効か、古くなったか」を判断してください。

現在時刻: {now}
評価基準:
- prospective（予定・約束）は実現済み・破棄済みなら expire、期日が明確なら reschedule で有効期限を提案
- 事実・状態を記す記憶は、内容が現在も正しいなら keep、陳腐化・反証されたなら expire または demote
- 判断に迷う場合は keep（変えない方が安全）

記憶リスト:
{memories}

以下の JSON のみを返してください（説明文は不要）:
{{"results": [{{"key": "<記憶のkey>", "verdict": "keep|expire|reschedule|demote", "valid_until_suggestion": "<ISO8601日時 or null>", "importance_suggestion": <0.0-1.0 or null>, "reason": "<短い理由>"}}]}}
"""


class FreshnessWorker:
    """LLM 鮮度評価 worker（ConsolidationWorker と同じ thread + graceful shutdown パターン）。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        cfg: FreshnessConfig = settings.freshness
        self._cfg = cfg
        self.interval_seconds = cfg.interval_seconds
        self.batch_size = cfg.batch_size
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._running:
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="freshness-worker")
        self._thread.start()
        logger.info("FreshnessWorker started (interval=%ds batch=%d)", self.interval_seconds, self.batch_size)

    def stop(self, timeout: float = 5.0) -> None:
        self._running = False
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("FreshnessWorker stopped")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_cycle()
            except Exception:
                logger.exception("Freshness cycle failed")
            self._stop_event.wait(self.interval_seconds)

    # ------------------------------------------------------------------
    # 1 cycle: persona 毎に SELECT → LLM 評価 → 適用
    # ------------------------------------------------------------------

    def run_cycle(self) -> None:
        """1 cycle 実行（手動運転・検証用に public）。全 persona を評価する。"""
        if not self._cfg.enabled:
            logger.debug("FreshnessWorker disabled, skip")
            return
        from nous.application.use_cases import AppContextRegistry

        try:
            personas = list(AppContextRegistry._contexts.keys())
        except Exception:
            logger.exception("FreshnessWorker: failed to list personas")
            return

        for persona in personas:
            try:
                ctx = AppContextRegistry.get(persona)
                self._evaluate_persona(ctx, persona)
            except Exception:
                logger.exception("FreshnessWorker: error for persona=%s", persona)

    # ------------------------------------------------------------------
    # SELECT
    # ------------------------------------------------------------------

    def _select_candidates(self, ctx, now: datetime) -> list[Memory]:
        """鮮度評価の対象記憶を選ぶ（lifecycle=active、gist/consolidated/expired 除外）。"""
        all_result = ctx.memory_repo.find_all()
        if not all_result.is_ok or not all_result.value:
            return []
        stale_delta = timedelta(days=self._cfg.stale_days)
        probe_delta = timedelta(days=self._cfg.expiry_probe_days)
        stale_cutoff = now - stale_delta
        probe_end = now + probe_delta

        candidates: list[Memory] = []
        for m in all_result.value:
            if m.lifecycle_status != "active":
                continue
            # gist ノード・consolidated ソースは機械 decay と同一のスキップ規約
            if getattr(m, "source_type", "") == "consolidated":
                continue
            valid_until = getattr(m, "valid_until", None)
            if valid_until is not None and valid_until <= now:
                continue  # 既に期限切れ → ConsolidationWorker の管轄
            updated_at = getattr(m, "updated_at", None) or m.created_at
            last_accessed = getattr(m, "last_accessed", None)

            # (a) 期限切れ近い記憶（7日以内に有効期限を迎える）
            near_expiry = valid_until is not None and valid_until <= probe_end
            # (b) 無期限 prospective が stale_days 以上未更新
            stale_prospective = getattr(m, "kind", "") == "prospective" and valid_until is None and updated_at < stale_cutoff
            # (c) stale_days 以上未アクセス（last_accessed が無ければ updated_at で判定）
            last_activity = max((t for t in (last_accessed, updated_at) if t is not None), default=updated_at)
            not_accessed = last_activity < stale_cutoff

            if near_expiry or stale_prospective or not_accessed:
                candidates.append(m)

        # importance 低いものを優先（protected の importance >= 0.8 は後ろ）
        candidates.sort(key=lambda m: (m.importance >= 0.8, -float(m.importance)))
        return candidates[: self.batch_size]

    # ------------------------------------------------------------------
    # LLM 評価
    # ------------------------------------------------------------------

    def _evaluate_persona(self, ctx, persona: str) -> None:
        """1 persona 分の SELECT → LLM 評価 → verdict 適用。"""
        from nous.domain.shared.time_utils import get_now

        now = get_now()
        candidates = self._select_candidates(ctx, now)
        if not candidates:
            return
        logger.info("FreshnessWorker: persona=%s evaluating %d memories", persona, len(candidates))

        try:
            text = self._ask_llm(candidates, now)
        except Exception as e:
            logger.warning("FreshnessWorker: LLM call failed: %s", e)
            self._record_error(ctx, persona, f"llm call failed: {e}")
            return
        if not text:
            self._record_error(ctx, persona, "llm returned no text")
            return

        try:
            verdicts = self._parse_verdicts(text)
        except Exception as e:
            logger.warning("FreshnessWorker: invalid LLM response: %s", e)
            self._record_error(ctx, persona, f"invalid llm response: {e}")
            return

        self._apply_verdicts(ctx, persona, candidates, verdicts, now)

    def _build_prompt(self, candidates: list[Memory], now: datetime) -> str:
        """batch prompt を組む（記憶本文は preview 切り詰め・key/kind/importance/期限を添付）。"""
        lines = []
        for m in candidates:
            valid_until = getattr(m, "valid_until", None)
            lines.append(
                json.dumps(
                    {
                        "key": m.key,
                        "content": m.content[:_CONTENT_PREVIEW_CHARS],
                        "kind": getattr(m, "kind", "semantic"),
                        "importance": round(float(m.importance), 2),
                        "valid_until": valid_until.isoformat() if valid_until else None,
                        "updated_at": (getattr(m, "updated_at", None) or m.created_at).isoformat(),
                    },
                    ensure_ascii=False,
                )
            )
        return _FRESHNESS_PROMPT.format(now=now.isoformat(), memories="\n".join(lines))

    # テスト差し替え用フック（monkeypatch でなくインスタンス属性で上書き可能に）
    _ask_llm_for_test: str | None = None
    _ask_llm_raise: Exception | None = None

    def _ask_llm(self, candidates: list[Memory], now: datetime) -> str | None:
        """batch prompt を LLM に投げ、生テキストを返す。"""
        # テスト用フック（実装はプロダクト経路と同一形だが外部依存を分離）
        if self._ask_llm_raise is not None:
            raise self._ask_llm_raise
        if self._ask_llm_for_test is not None:
            return self._ask_llm_for_test

        cfg = self._cfg
        api_key = cfg.get_effective_api_key(self._settings)
        if not api_key:
            raise RuntimeError("freshness LLM api_key is not configured")

        from nous.infrastructure.llm.base import LLMMessage
        from nous.infrastructure.llm.factory import get_provider
        from nous.infrastructure.llm.text_utils import collect_text

        provider: LLMProvider = get_provider(cfg.provider, api_key, cfg.model, cfg.base_url)
        prompt = self._build_prompt(candidates, now)
        return asyncio.run(
            collect_text(
                provider,
                messages=[LLMMessage(role="user", content=prompt)],
                system="",
                tools=None,
                temperature=0.0,
                max_tokens=16000,  # reasoning LLM は reasoning token が max_tokens を消費するため大き目に取る
            )
        )

    def _parse_verdicts(self, text: str) -> list[dict]:
        """LLM 応答をパース（{"results": [...]} 配列。前後の説明文・コードフェンスは許容）。"""
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.startswith("json"):
                stripped = stripped[4:]
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no JSON object found in response")
        data = json.loads(stripped[start : end + 1])
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise ValueError("missing 'results' array")
        return [r for r in results if isinstance(r, dict) and isinstance(r.get("key"), str)]

    # ------------------------------------------------------------------
    # 適用 + 監査記録
    # ------------------------------------------------------------------

    def _apply_verdicts(self, ctx, persona: str, candidates: list[Memory], verdicts: list[dict], now: datetime) -> None:
        """verdict を memory に適用し、記憶毎に session_events へ 1 行記録する。"""
        by_key = {m.key: m for m in candidates}
        applied = 0
        for v in verdicts:
            key = v["key"]
            mem = by_key.get(key)
            if mem is None:
                continue  # LLM が候補外の key を返した → 無視
            try:
                updates = self._resolve_updates(mem, v)
                if updates:
                    result = ctx.memory_service.update_memory(key, **updates)
                    if getattr(result, "is_ok", False):
                        applied += 1
                    else:
                        self._record_error(ctx, persona, f"update_memory failed for {key}: {result}")
                        continue
                self._record_verdict(ctx, persona, key, v, updates, mem)
            except Exception as e:
                logger.warning("FreshnessWorker: verdict apply failed for %s: %s", key, e)
                self._record_error(ctx, persona, f"verdict apply failed for {key}: {e}")

        logger.info("FreshnessWorker: persona=%s applied %d/%d verdicts", persona, applied, len(verdicts))

    def _resolve_updates(self, mem: Memory, verdict: dict) -> dict:
        """verdict → update_memory kwargs（不正値は黙って捨てる）。"""
        verdict_type = verdict.get("verdict")
        updates: dict = {}
        suggestion = verdict.get("valid_until_suggestion")
        if verdict_type == "expire":
            updates["lifecycle_status"] = "archived"
        elif verdict_type == "reschedule":
            if suggestion:
                updates["valid_until"] = self._parse_datetime(suggestion)
        elif verdict_type == "demote":
            imp = verdict.get("importance_suggestion")
            # importance >= 0.8 は protected — demote を適用しない（valid_until 系のみ可）
            if isinstance(imp, (int, float)) and not isinstance(imp, bool) and mem.importance < 0.8:
                updates["importance"] = float(max(0.0, min(1.0, imp)))
            elif suggestion:
                updates["valid_until"] = self._parse_datetime(suggestion)
        return updates

    @staticmethod
    def _parse_datetime(raw: object) -> datetime | None:
        """ISO8601 文字列を datetime へ（パース不能は None = 更新しない）。"""
        if not isinstance(raw, str) or not raw.strip():
            return None
        try:
            from datetime import datetime as dt

            return dt.fromisoformat(raw.strip())
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # session_events 監査記録
    # ------------------------------------------------------------------

    def _record_verdict(self, ctx, persona: str, key: str, verdict: dict, updates: dict, mem: Memory) -> None:
        """verdict 毎に 1 行（適用前値 + verdict + 理由）。ops が undo 判断に使う。"""
        from nous.domain.memory.session_event import SessionEvent
        from nous.domain.shared.time_utils import get_now
        from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

        summary = f"{verdict.get('verdict', '?')} {key}: {verdict.get('reason', '')}"[:200]
        mem_valid_until = getattr(mem, "valid_until", None)
        detail = json.dumps(
            {
                "memory_key": key,
                "verdict": verdict,
                "applied_updates": {k: str(v) for k, v in updates.items()},
                "before": {
                    "importance": mem.importance,
                    "valid_until": mem_valid_until.isoformat() if mem_valid_until else None,
                    "lifecycle_status": mem.lifecycle_status,
                },
            },
            ensure_ascii=False,
            default=str,
        )
        SessionEventRepository(ctx.connection).insert(
            SessionEvent(
                session_id="freshness_worker",
                persona=persona,
                event_type="freshness.verdict",
                timestamp=get_now(),
                summary=summary,
                detail=detail,
                metadata=None,
            )
        )

    def _record_error(self, ctx, persona: str, message: str) -> None:
        """失敗も監査可能にする（summary="error: ..."）。memory への書込みはしない。"""
        try:
            from nous.domain.memory.session_event import SessionEvent
            from nous.domain.shared.time_utils import get_now
            from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

            SessionEventRepository(ctx.connection).insert(
                SessionEvent(
                    session_id="freshness_worker",
                    persona=persona,
                    event_type="freshness.verdict",
                    timestamp=get_now(),
                    summary=f"error: {message}"[:200],
                    detail=None,
                    metadata=None,
                )
            )
        except Exception:
            logger.exception("FreshnessWorker: failed to record error event")
