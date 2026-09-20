"""Consolidation Worker — CraniMem-inspired two-layer (CLS) consolidation.

Replaces the old date-based extractive summarization worker.
Operates on archived memories (set by DecayWorker) and entity clusters:

1. Finds archived memories (lifecycle_status='archived', set by DecayWorker)
   that are still valid (valid_until IS NULL — F2 bitemporal contract:
   superseded memories are never gistified)
2. Groups by shared entity relations (entity_relations table)
3. Creates gist summaries from the semantic layer only; episodic memories
   stay raw (never deleted, never merged into the gist)
4. Links gist to semantic sources via related_keys + derived_from, marked
   kind='semantic' / source_type='consolidated', plus per-source
   memory_links rows (link_type='summarizes', source memory → gist node)

ADR: archived → tombstoned transition is NOT performed. Consolidated
sources stay archived (queryable history); tombstone remains reserved
for explicit user deletion (F2 contract).

Philosophy: "Memories don't disappear — they consolidate."
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from typing import TYPE_CHECKING, Any

from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.sqlite.mot_thoughts import MOT_CONFIDENCE_THRESHOLD

if TYPE_CHECKING:
    from nous.config.settings import Settings

logger = get_logger(__name__)

#: audit H1 — default cap on LLM calls per consolidation cycle.
DEFAULT_LLM_GIST_MAX_PER_CYCLE = 5

_GIST_PROMPT = """あなたは記憶の統合器です。以下は同じ話題についての複数の記憶です。

{memories}

指示:
- 個々の出来事の列挙ではなく、そこから抽出できる一般化された知識・規則性・教訓を述べる
- 元の記憶に無い事実を創作しない（幻覚禁止）
- 日本語で 1〜5 行、各行は "- " で始める
- 見出し行は不要。要約本文のみを出力する"""


def _cfg_value(config: Any, name: str, default: Any) -> Any:
    """Read a consolidation knob defensively.

    Settings may be a plain mock in tests; only scalar values are accepted so a
    missing/mocked attribute cannot silently enable LLM calls.
    """
    if config is None:
        return default
    value = getattr(config, name, default)
    if isinstance(value, (bool, int, float, str)):
        return value
    return default


def _cfg_number(config: Any, name: str, default: Any, cast: Any) -> Any:
    """Read a numeric consolidation knob, ignoring malformed values."""
    try:
        return cast(_cfg_value(config, name, default))
    except (TypeError, ValueError):
        return default


def _resolve_gist_llm(settings: Any) -> tuple[str, str, str, str] | None:
    """Resolve (provider, api_key, model, base_url) for gist generation.

    Explicit ``consolidation.*`` values win; otherwise the memory-enrichment LLM
    settings are reused (same provider/key conventions). Returns None when no
    usable credential exists — the caller then keeps the concatenation fallback.
    """
    cfg = getattr(settings, "consolidation", None)
    enrichment = getattr(settings, "memory_enrichment", None)

    provider = str(_cfg_value(cfg, "provider", "") or _cfg_value(enrichment, "provider", "openrouter"))
    model = str(_cfg_value(cfg, "model", "") or _cfg_value(enrichment, "model", ""))
    base_url = str(_cfg_value(cfg, "base_url", "") or _cfg_value(enrichment, "base_url", ""))
    api_key = str(_cfg_value(cfg, "api_key", "") or "")
    if not api_key and enrichment is not None:
        resolver = getattr(enrichment, "get_effective_api_key", None)
        if callable(resolver):
            try:
                api_key = str(resolver(settings) or "")
            except Exception:
                logger.debug("gist LLM key resolution failed", exc_info=True)
                api_key = ""
    if not api_key or not model:
        return None
    return provider, api_key, model, base_url


def _gist_prompt(memories: list, max_chars: int) -> str:
    """Render the gist prompt, bounding the source text (cost control)."""
    lines: list[str] = []
    budget = max_chars
    for mem in memories:
        content = (getattr(mem, "content", "") or "").strip()
        if not content:
            continue
        entry = f"- {content[:500]}"
        if len(entry) > budget:
            entry = entry[:budget]
        if not entry:
            break
        lines.append(entry)
        budget -= len(entry)
        if budget <= 0:
            break
    return _GIST_PROMPT.format(memories="\n".join(lines))


async def _generate_gist_async(settings: Any, memories: list) -> str | None:
    """Call the LLM once and return the generalized gist, or None on failure."""
    resolved = _resolve_gist_llm(settings)
    if resolved is None:
        logger.debug("ConsolidationWorker: no gist LLM credentials; using concatenation fallback")
        return None
    provider_name, api_key, model, base_url = resolved
    cfg = getattr(settings, "consolidation", None)
    max_chars = _cfg_number(cfg, "llm_gist_max_chars", 4000, int)
    max_tokens = _cfg_number(cfg, "llm_gist_max_tokens", 512, int)
    temperature = _cfg_number(cfg, "llm_gist_temperature", 0.0, float)

    from nous.infrastructure.llm.base import LLMMessage
    from nous.infrastructure.llm.factory import get_provider
    from nous.infrastructure.llm.text_utils import collect_text

    provider = get_provider(provider_name, api_key, model, base_url)
    text = await collect_text(
        provider,
        messages=[LLMMessage(role="user", content=_gist_prompt(memories, max_chars))],
        system="",
        tools=[],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    gist = (text or "").strip()
    return gist or None


def default_gist_llm(settings: Any, memories: list) -> str | None:
    """Sync wrapper used by the worker thread (same pattern as _save_consolidated)."""
    if len(memories) < 2:
        return None
    try:
        return asyncio.run(_generate_gist_async(settings, memories))
    except Exception:
        logger.warning("ConsolidationWorker: LLM gist failed; falling back to concatenation", exc_info=True)
        return None


def _memory_entity_map(entity_repo, memory_keys: list[str]) -> dict[str, set[str]]:
    """Map memory_key → entity ids with one batch query (N+1 avoidance).

    Uses ``get_entities_for_memories`` when available; falls back to
    per-memory ``get_memory_entities`` for legacy repos.
    """
    result: dict[str, set[str]] = {k: set() for k in memory_keys}
    get_batch = getattr(entity_repo, "get_entities_for_memories", None)
    if get_batch is not None:
        try:
            for row in get_batch(list(memory_keys), limit=50) or []:
                key = row.get("memory_key")
                eid = row.get("id")
                if key in result and eid:
                    result[key].add(eid)
            return result
        except Exception:
            logger.exception("ConsolidationWorker: batch entity fetch failed; falling back")
    for key in memory_keys:
        try:
            ent_result = entity_repo.get_memory_entities(key)
        except Exception:
            logger.exception("ConsolidationWorker: entity fetch failed for %s", key)
            continue
        if ent_result.is_ok and ent_result.value:
            result[key] = {e.id for e in ent_result.value}
    return result


def _semantic_layer(memories: list) -> list:
    """Semantic layer of a group (episodic stays raw — never gistified)."""
    return [m for m in memories if getattr(m, "kind", "semantic") == "semantic"]


class ConsolidationWorker:
    """Periodically consolidates archived memories into merged summaries."""

    def __init__(self, settings: Settings, gist_llm: Any = None) -> None:
        self._settings = settings
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.interval_seconds = 86400  # 24 hours
        self.min_memories_per_group = 3
        self.max_consolidated = 10
        # audit H1 — LLM gist generation (integration/generalization) with a
        # per-cycle call cap and content-hash reuse of identical clusters.
        self._gist_llm = gist_llm if gist_llm is not None else default_gist_llm
        cfg = getattr(settings, "consolidation", None)
        self.gist_llm_enabled = bool(_cfg_value(cfg, "llm_gist_enabled", True))
        self.gist_llm_max_per_cycle = _cfg_number(cfg, "llm_gist_max_per_cycle", DEFAULT_LLM_GIST_MAX_PER_CYCLE, int)
        self.gist_llm_min_memories = _cfg_number(cfg, "llm_gist_min_memories", 2, int)
        self._gist_cache: dict[str, str] = {}
        self._llm_calls_this_cycle = 0

    def start(self) -> None:
        """Start the background consolidation thread."""
        if self._running:
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="consolidation-worker")
        self._thread.start()
        logger.info("ConsolidationWorker started (interval=%ds)", self.interval_seconds)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the background thread and wait for it to finish."""
        self._running = False
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("ConsolidationWorker stopped")

    def _run(self) -> None:
        """Main loop: consolidate then wait (interruptible)."""
        while not self._stop_event.is_set():
            try:
                self._consolidate_all()
            except Exception:
                logger.exception("Consolidation cycle failed")
            self._stop_event.wait(self.interval_seconds)

    def _consolidate_all(self) -> None:
        """Run consolidation for all active personas."""
        from nous.application.use_cases import AppContextRegistry

        # audit H1 — cost control: the LLM gist budget is per cycle, not per persona.
        self._llm_calls_this_cycle = 0

        try:
            personas = list(AppContextRegistry._contexts.keys())
        except Exception:
            logger.exception("ConsolidationWorker: failed to list personas")
            return

        for persona in personas:
            try:
                ctx = AppContextRegistry.get(persona)
                self._consolidate_persona(ctx, persona)
            except Exception:
                logger.exception("ConsolidationWorker: error for persona=%s", persona)

    @staticmethod
    def _cluster_digest(memories: list) -> str:
        """Content hash of a cluster — identical clusters reuse the cached gist."""
        hasher = hashlib.sha256()
        for mem in sorted(memories, key=lambda m: str(getattr(m, "key", ""))):
            hasher.update(str(getattr(mem, "key", "")).encode("utf-8"))
            hasher.update(b"|")
            hasher.update(str(getattr(mem, "content", "")).encode("utf-8"))
            hasher.update(b"\n")
        return hasher.hexdigest()[:32]

    def _consolidate_persona(self, ctx, persona: str) -> None:
        """Consolidate archived memories for a single persona."""
        # 1. Find all non-tombstoned memories, filter for archived + still valid.
        #    Superseded (valid_until set) memories are F2 history — never gistified.
        all_result = ctx.memory_repo.find_all()
        if not all_result.is_ok or not all_result.value:
            return

        archived = [
            m for m in all_result.value if m.lifecycle_status == "archived" and getattr(m, "valid_until", None) is None
        ]
        if len(archived) < self.min_memories_per_group:
            logger.debug(
                "ConsolidationWorker: %s has %d archived (< %d)", persona, len(archived), self.min_memories_per_group
            )
            return

        logger.info("ConsolidationWorker: %s has %d archived memories", persona, len(archived))

        # 2. Build memory → entity IDs mapping (single batch query)
        mem_entities = _memory_entity_map(ctx.entity_repo, [m.key for m in archived])

        # 3. Group by shared entities
        groups = self._group_by_entities(archived, mem_entities)
        logger.info("ConsolidationWorker: %s grouped into %d entity clusters", persona, len(groups))

        # 4. Consolidate each group
        consolidated_count = 0
        # Sort groups by size descending
        sorted_groups = sorted(groups.items(), key=lambda x: -len(x[1]))
        for entity_key, memories in sorted_groups:
            if consolidated_count >= self.max_consolidated:
                break
            if len(memories) < self.min_memories_per_group:
                continue

            content = self._build_consolidated(memories)
            if content:
                # audit H1 — provenance: episodic members of the cluster are the
                # episodes the gist was generalized from; they are recorded as
                # contextual links (never merged, per the CLS two-layer ADR).
                context_keys = [m.key for m in memories if getattr(m, "kind", "semantic") != "semantic"]
                self._save_consolidated(ctx, content, memories, entity_key, context_keys=context_keys)
                consolidated_count += 1

        logger.info(
            "ConsolidationWorker: %s complete — %d new consolidated memories",
            persona,
            consolidated_count,
        )

    def _group_by_entities(
        self,
        memories: list,
        mem_entities: dict[str, set[str]],
    ) -> dict[str, list]:
        """Group archived memories by shared entity clusters.

        Memories that share entity IDs are grouped together.
        Ungrouped memories start their own singleton group.
        """
        groups: dict[str, list] = {}
        assigned: set[str] = set()

        for mem in memories:
            if mem.key in assigned:
                continue
            # Find the best existing group or start a new one
            best_group: str | None = None
            best_overlap = 0
            for group_key, group_mems in groups.items():
                group_entities: set[str] = set()
                for gm in group_mems:
                    group_entities |= mem_entities.get(gm.key, set())
                overlap = len(mem_entities.get(mem.key, set()) & group_entities)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_group = group_key

            if best_group is not None and best_overlap > 0:
                groups[best_group].append(mem)
            else:
                groups[mem.key] = [mem]
            assigned.add(mem.key)

        return groups

    def _build_consolidated(self, memories: list) -> str | None:
        """Build a gist from the semantic layer of a group (CLS two-layer).

        Semantic memories are distilled via :meth:`_build_gist`; episodic
        memories stay raw — never merged, never deleted.
        Returns None when the group has no semantic layer (episodic-only).
        """
        if not memories:
            return None
        semantic = _semantic_layer(memories)
        if not semantic:
            return None
        return self._build_gist(semantic)

    def _build_gist(self, memories: list) -> str | None:
        """Build a gist from semantic memories (audit H1).

        Order: cached gist (content hash) → LLM integration/generalization →
        concatenation fallback. The LLM path is capped per cycle
        (``llm_gist_max_per_cycle``) and skipped when disabled or when no
        credentials resolve, so cost never exceeds the v3.9 behaviour.
        """
        if not memories:
            return None

        digest = self._cluster_digest(memories)
        cached = self._gist_cache.get(digest)
        if cached:
            return cached

        text: str | None = None
        if (
            self.gist_llm_enabled
            and len(memories) >= self.gist_llm_min_memories
            and self._llm_calls_this_cycle < self.gist_llm_max_per_cycle
        ):
            # Count the attempt: a failed call still consumed the budget.
            self._llm_calls_this_cycle += 1
            try:
                text = self._gist_llm(self._settings, memories)
            except Exception:
                logger.warning("ConsolidationWorker: gist LLM raised; falling back", exc_info=True)
                text = None

        if isinstance(text, str) and text.strip():
            gist = text.strip()
            self._gist_cache[digest] = gist
            return gist

        return self._concat_gist(memories)

    def _concat_gist(self, memories: list) -> str | None:
        """Extractive concatenation — the pre-v4.0 gist and the LLM fallback."""
        if not memories:
            return None

        def _sort_key(m) -> str:
            created = m.created_at
            if isinstance(created, str):
                return created
            return created.isoformat() if created is not None else ""

        memories_sorted = sorted(memories, key=_sort_key, reverse=True)
        lines = [f"## Consolidated Gist ({len(memories)} merged)"]

        for mem in memories_sorted[:20]:  # cap at 20 per group
            created = mem.created_at
            if isinstance(created, str):
                date_str = created[:10]
            elif created is not None:
                date_str = created.date().isoformat()
            else:
                date_str = "?"
            content_preview = mem.content[:200] if mem.content else "(empty)"
            lines.append(f"- [{date_str}] {content_preview}")

        return "\n".join(lines)

    def _link_summarizes(self, ctx, gist_key: str | None, source_keys: list[str]) -> None:
        """Link each source memory → gist node in memory_links (link_type='summarizes').

        Best-effort per the wiring convention: a failed link never fails
        consolidation. ``upsert_link`` emits ``link_fire`` internally with
        its own try/except — no additional emit here.
        """
        if not gist_key:
            return
        upsert = getattr(ctx.entity_repo, "upsert_link", None)
        if upsert is None:
            return
        for key in source_keys:
            try:
                upsert(key, gist_key, link_type="summarizes")
            except Exception:
                logger.debug("summarizes link failed for %s -> %s", key, gist_key, exc_info=True)

    def _link_contextual(self, ctx, gist_key: str | None, context_keys: list[str] | None) -> None:
        """Link episodic context memories → gist node (link_type='contextual').

        audit H1 provenance: the gist loses detail (fuzzy trace), so the episodes
        it was generalized from stay reachable from the gist. Best-effort.
        """
        if not gist_key or not context_keys:
            return
        upsert = getattr(ctx.entity_repo, "upsert_link", None)
        if upsert is None:
            return
        for key in context_keys:
            try:
                upsert(key, gist_key, link_type="contextual")
            except Exception:
                logger.debug("contextual link failed for %s -> %s", key, gist_key, exc_info=True)

    def _save_consolidated(
        self,
        ctx,
        content: str,
        sources: list,
        entity_key: str,
        context_keys: list[str] | None = None,
    ) -> None:
        """Save the gist memory and link it to semantic sources.

        Provenance: kind='semantic' / source_type='consolidated' /
        derived_from=[source keys as JSON]. Sources stay archived —
        no archived → tombstoned transition (ADR).
        """
        sources = _semantic_layer(sources)
        if not sources:
            return
        avg_importance = sum(m.importance for m in sources) / len(sources) if sources else 0.5
        source_keys = [m.key for m in sources]
        # audit H1 — provenance is mandatory for new gists (no NULL derived_from).
        if not source_keys:
            return

        result = asyncio.run(
            ctx.memory_service.create_memory(
                content=content,
                importance=avg_importance,
                emotion="neutral",
                emotion_intensity=0.0,
                tags=["consolidated", "auto"],
                privacy_level="private",
                source_context="consolidation_worker",
                related_keys=source_keys,
                kind="semantic",
                source_type="consolidated",
                derived_from=json.dumps(source_keys, ensure_ascii=False),
            )
        )

        if result.is_ok:
            gist_key = getattr(result.value, "key", None)
            self._link_summarizes(ctx, gist_key, source_keys)
            self._link_contextual(ctx, gist_key, context_keys)
            logger.info(
                "Consolidated %d memories into key=%s (entity=%s)",
                len(sources),
                result.value,
                entity_key,
            )

        # MoT: high-confidence trace goes to a separate slot (F5).
        # Corrosion/TTL live on mot_thoughts only — never double-decayed
        # with memory_strength / memory_links.
        if result.is_ok and avg_importance >= MOT_CONFIDENCE_THRESHOLD:
            try:
                from nous.infrastructure.sqlite.mot_thoughts import save_thought  # noqa: PLC0415

                gist_key = getattr(result.value, "key", None)
                db = getattr(ctx.memory_repo, "_db", None)
                if gist_key is not None and db is not None:
                    save_thought(
                        db,
                        key=f"mot_{gist_key}",
                        consolidation_key=gist_key,
                        trace=content,
                        confidence=avg_importance,
                    )
            except Exception:
                logger.debug("MoT thought save failed", exc_info=True)
