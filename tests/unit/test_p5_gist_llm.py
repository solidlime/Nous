"""P5 tests — audit H1: LLM gist integration/generalization with bounded cost + provenance."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from nous.application.workers.consolidation_worker import ConsolidationWorker
from nous.config.settings import ConsolidationConfig
from nous.domain.memory.entities import Memory
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now

PROVIDER_CALLS: dict = {"calls": []}


def _mem(key: str, content: str = "内容", kind: str = "semantic", archived: bool = True) -> Memory:
    now = get_now()
    return Memory(
        key=key,
        content=content,
        created_at=now,
        updated_at=now,
        importance=0.6,
        kind=kind,
        lifecycle_status="archived" if archived else "active",
    )


def _settings(**consolidation) -> MagicMock:
    settings = MagicMock()
    cfg = ConsolidationConfig(**consolidation)
    settings.consolidation = cfg
    settings.memory_enrichment = MagicMock()
    settings.memory_enrichment.provider = "openrouter"
    settings.memory_enrichment.model = "openai/gpt-4o-mini"
    settings.memory_enrichment.base_url = "https://example.invalid/v1"
    settings.memory_enrichment.get_effective_api_key.return_value = "test-key"
    return settings


class _Service:
    """Records create_memory calls (same shape as the cls consolidation tests)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_memory(self, **kwargs):
        self.calls.append(kwargs)
        created = MagicMock()
        created.key = f"gist{len(self.calls)}"
        return Success(created)


class _Repo:
    def __init__(self, memories: list) -> None:
        self._memories = memories
        self.links: list[tuple] = []

    def find_all(self):
        return Success(self._memories)


class _EntityRepo:
    def __init__(self) -> None:
        self.links: list[tuple] = []

    def get_entities_for_memories(self, keys, limit=50):
        # one shared entity → all memories land in one cluster
        return [{"memory_key": k, "id": "e1"} for k in keys]

    def upsert_link(self, source, target, link_type="semantic", **kwargs):
        self.links.append((source, target, link_type))
        return Success(None)


def _group(size: int, prefix: str = "sem") -> list[Memory]:
    return [_mem(f"{prefix}{i}", f"記憶その{i}") for i in range(size)]


class TestGistLLMPath:
    def test_llm_gist_is_used_and_cached(self):
        calls: list[list] = []

        def fake_llm(settings, memories):
            calls.append(list(memories))
            return "- 一般化された教訓\n- 規則性"

        worker = ConsolidationWorker(_settings(), gist_llm=fake_llm)
        group = _group(3)

        assert worker._build_gist(group) == "- 一般化された教訓\n- 規則性"
        assert len(calls) == 1
        # identical cluster → cache hit, no second LLM call
        assert worker._build_gist(group) == "- 一般化された教訓\n- 規則性"
        assert len(calls) == 1

    def test_llm_failure_falls_back_to_concatenation(self):
        def boom(settings, memories):
            raise RuntimeError("provider down")

        worker = ConsolidationWorker(_settings(), gist_llm=boom)
        gist = worker._build_gist(_group(3))
        assert gist is not None
        assert "Consolidated Gist (3 merged)" in gist
        assert "記憶その0" in gist

    def test_llm_none_result_falls_back(self):
        worker = ConsolidationWorker(_settings(), gist_llm=lambda s, m: None)
        gist = worker._build_gist(_group(2))
        assert gist is not None and "Consolidated Gist (2 merged)" in gist

    def test_blank_llm_output_falls_back(self):
        worker = ConsolidationWorker(_settings(), gist_llm=lambda s, m: "   \n ")
        gist = worker._build_gist(_group(2))
        assert gist is not None and "Consolidated Gist (2 merged)" in gist

    def test_disabled_knob_never_calls_llm(self):
        calls: list = []
        worker = ConsolidationWorker(
            _settings(llm_gist_enabled=False),
            gist_llm=lambda s, m: calls.append(1) or "llm",
        )
        gist = worker._build_gist(_group(3))
        assert calls == []
        assert gist is not None and "Consolidated Gist" in gist

    def test_single_memory_cluster_skips_llm(self):
        calls: list = []
        worker = ConsolidationWorker(_settings(), gist_llm=lambda s, m: calls.append(1) or "llm")
        assert worker._build_gist(_group(1)) is not None
        assert calls == []


class TestCostCap:
    def test_calls_are_capped_per_cycle(self):
        calls: list = []

        def fake_llm(settings, memories):
            calls.append(1)
            return f"llm-{len(calls)}"

        worker = ConsolidationWorker(_settings(llm_gist_max_per_cycle=2), gist_llm=fake_llm)
        worker._llm_calls_this_cycle = 0
        texts = [worker._build_gist(_group(3, prefix=f"p{i}_")) for i in range(4)]

        assert len(calls) == 2, "LLM は 1 サイクル 2 回までに制限される"
        assert texts[0] == "llm-1"
        assert texts[1] == "llm-2"
        # budget exhausted → concatenation fallback, still a usable gist
        assert "Consolidated Gist" in (texts[2] or "")
        assert "Consolidated Gist" in (texts[3] or "")

    def test_budget_resets_each_cycle(self):
        worker = ConsolidationWorker(_settings(llm_gist_max_per_cycle=1), gist_llm=lambda s, m: "llm")
        worker._llm_calls_this_cycle = 5
        assert worker._build_gist(_group(3)) is not None  # budget exhausted → fallback
        fallback = worker._build_gist(_group(3, prefix="other_"))
        assert fallback is not None and "Consolidated Gist" in fallback

    def test_failed_call_consumes_budget(self):
        calls: list = []

        def boom(settings, memories):
            calls.append(1)
            return None

        worker = ConsolidationWorker(_settings(llm_gist_max_per_cycle=1), gist_llm=boom)
        worker._build_gist(_group(2, prefix="a_"))
        worker._build_gist(_group(2, prefix="b_"))
        assert len(calls) == 1


class TestConsolidationProvenance:
    def _ctx(self, memories: list):
        ctx = MagicMock()
        ctx.memory_repo = _Repo(memories)
        ctx.entity_repo = _EntityRepo()
        ctx.memory_service = _Service()
        return ctx

    def _run(self, ctx, gist_llm=None, **consolidation):
        worker = ConsolidationWorker(_settings(**consolidation), gist_llm=gist_llm or (lambda s, m: "LLM gist 本文"))
        worker._consolidate_persona(ctx, "test")
        return worker, ctx

    def test_gist_keeps_provenance_of_all_sources(self):
        memories = _group(3)
        ctx = self._ctx(memories)
        service: _Service = ctx.memory_service

        worker = ConsolidationWorker(_settings(), gist_llm=lambda s, m: "LLM gist 本文")
        worker._save_consolidated(ctx, "LLM gist 本文", memories, "e1")

        call = service.calls[0]
        assert call["content"] == "LLM gist 本文"
        assert call["derived_from"] is not None
        assert sorted(json.loads(call["derived_from"])) == ["sem0", "sem1", "sem2"]
        assert sorted(call["related_keys"]) == ["sem0", "sem1", "sem2"]
        assert call["source_type"] == "consolidated"

    def test_empty_sources_are_not_saved(self):
        ctx = MagicMock()
        service = _Service()
        ctx.memory_service = service
        worker = ConsolidationWorker(_settings())
        worker._save_consolidated(ctx, "gist", [], "e1")
        assert service.calls == []

    def test_episodic_context_is_linked_contextually(self):
        memories = [_mem("sem0"), _mem("sem1"), _mem("ep0", kind="episodic")]
        ctx = self._ctx(memories)
        service = _Service()
        ctx.memory_service = service
        worker = ConsolidationWorker(_settings())
        context_keys = [m.key for m in memories if m.kind != "semantic"]
        worker._save_consolidated(ctx, "gist", memories, "e1", context_keys=context_keys)

        links = ctx.entity_repo.links
        assert ("sem0", "gist1", "summarizes") in links
        assert ("sem1", "gist1", "summarizes") in links
        # episodic memories are never merged but stay reachable from the gist
        assert ("ep0", "gist1", "contextual") in links
        assert "ep0" not in json.loads(service.calls[0]["derived_from"])

    def test_consolidate_persona_uses_llm_gist(self):
        memories = _group(3)
        ctx = self._ctx(memories)
        service = _Service()
        ctx.memory_service = service
        calls: list = []

        def fake_llm(settings, mems):
            calls.append(1)
            return "統合された一般化"

        worker = ConsolidationWorker(_settings(), gist_llm=fake_llm)
        worker._consolidate_persona(ctx, "test")

        assert calls == [1]
        assert service.calls[0]["content"] == "統合された一般化"


class TestClusterDigest:
    def test_same_content_same_digest(self):
        a = ConsolidationWorker._cluster_digest(_group(2))
        b = ConsolidationWorker._cluster_digest(_group(2))
        assert a == b

    def test_content_change_changes_digest(self):
        a = ConsolidationWorker._cluster_digest(_group(2))
        changed = _group(2)
        changed[0].content = "別の内容"
        assert ConsolidationWorker._cluster_digest(changed) != a


class TestPromptBudget:
    def test_prompt_truncates_source_text(self):
        from nous.application.workers.consolidation_worker import _gist_prompt

        memories = [_mem(f"m{i}", "あ" * 500) for i in range(10)]
        prompt = _gist_prompt(memories, max_chars=200)
        assert len(prompt) < 1200
        assert "幻覚禁止" in prompt

    def test_resolves_credentials_from_enrichment(self):
        from nous.application.workers.consolidation_worker import _resolve_gist_llm

        resolved = _resolve_gist_llm(_settings())
        assert resolved is not None
        provider, api_key, model, _base_url = resolved
        assert (provider, api_key, model) == ("openrouter", "test-key", "openai/gpt-4o-mini")

    def test_missing_key_means_no_llm(self):
        from nous.application.workers.consolidation_worker import _resolve_gist_llm

        settings = _settings()
        settings.memory_enrichment.get_effective_api_key.return_value = ""
        assert _resolve_gist_llm(settings) is None

    def test_mocked_settings_do_not_enable_llm(self):
        """Legacy tests pass MagicMock settings — must never attempt a real LLM call."""
        from nous.application.workers.consolidation_worker import _resolve_gist_llm

        assert _resolve_gist_llm(MagicMock()) is None

    def test_llm_gist_async_returns_none_without_credentials(self):
        import asyncio

        from nous.application.workers.consolidation_worker import _generate_gist_async

        settings = _settings()
        settings.memory_enrichment.get_effective_api_key.return_value = ""
        assert asyncio.run(_generate_gist_async(settings, _group(2))) is None


@pytest.mark.parametrize("size", [2, 3, 20])
def test_concat_gist_caps_lines(size: int):
    worker = ConsolidationWorker(_settings(llm_gist_enabled=False), gist_llm=lambda s, m: None)
    gist = worker._build_gist(_group(size))
    assert gist is not None
    assert len(gist.splitlines()) == min(size, 20) + 1
