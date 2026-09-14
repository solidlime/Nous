"""Tests for brain_llm_* resolution chain in AppContext._init_enricher (Task B1).

Covers: ON/OFF × cfg None/present × provider match/mismatch × empty-field
fallback × reload_enricher swap.
"""

from __future__ import annotations

import logging

from nous.application.chat.introspection import _resolve_brain_llm_params
from nous.application.use_cases import AppContext
from nous.domain.chat_config import ChatConfig
from nous.domain.provider_config import ProviderConfig


class _MemoryEnrichmentCfg:
    """Standalone settings.memory_enrichment stand-in (cfg None path)."""

    enabled = True
    provider = "openrouter"
    api_key = None
    model = "openai/gpt-4o-mini"
    base_url = "https://openrouter.ai/api/v1"
    min_chars = 10

    def get_effective_api_key(self, settings) -> str:  # noqa: ANN001
        return "legacy-key"


class _Settings:
    openrouter_api_key = ""
    anthropic_api_key = ""
    openai_api_key = ""
    google_api_key = ""
    opencode_go_api_key = ""
    memory_enrichment = _MemoryEnrichmentCfg()


def _ctx(cfg: ChatConfig | None) -> AppContext:
    """Bare AppContext with only what _init_enricher touches."""
    ctx = object.__new__(AppContext)
    ctx._config = cfg  # noqa: SLF001
    ctx.settings = _Settings()  # noqa: SLF001
    return ctx


def _cfg(**session_overrides) -> ChatConfig:
    """ChatConfig with provider_config + session overrides via flat keys."""
    data = {
        "memory_enrichment_enabled": True,
        "provider_config": ProviderConfig(
            provider="anthropic", model="chat-model", api_key="chat-key", base_url="https://chat.url/v1"
        ),
    }
    data.update(session_overrides)
    return ChatConfig(**data)


class TestCfgNone:
    def test_uses_legacy_settings_chain(self):
        """cfg None → settings.memory_enrichment chain unchanged."""
        ctx = _ctx(None)
        ctx._init_enricher()
        assert ctx._enricher is not None
        assert ctx._enricher._provider_name == "openrouter"
        assert ctx._enricher._model == "openai/gpt-4o-mini"
        assert ctx._enricher._api_key == "legacy-key"
        assert ctx._enricher._base_url == "https://openrouter.ai/api/v1"


class TestToggleOff:
    def test_uses_chat_four_piece_set(self):
        """OFF → chat provider/model/base_url/api_key, no mixed provider."""
        ctx = _ctx(_cfg())
        ctx._init_enricher()
        e = ctx._enricher
        assert e is not None
        assert e._provider_name == "anthropic"
        assert e._model == "chat-model"
        assert e._base_url == "https://chat.url/v1"
        assert e._api_key == "chat-key"


class TestToggleOn:
    def test_dedicated_values_win(self):
        """ON with all brain_llm_* set → dedicated 4-piece."""
        cfg = _cfg(
            brain_llm_dedicated=True,
            brain_llm_provider="openai",
            brain_llm_model="brain-model",
            brain_llm_base_url="https://brain.url/v1",
            brain_llm_api_key="brain-key",
        )
        ctx = _ctx(cfg)
        ctx._init_enricher()
        e = ctx._enricher
        assert e is not None
        assert e._provider_name == "openai"
        assert e._model == "brain-model"
        assert e._base_url == "https://brain.url/v1"
        assert e._api_key == "brain-key"

    def test_empty_fields_fall_back_to_settings_chain(self, monkeypatch):
        """ON with empty fields → settings.memory_enrichment fallback chain."""
        monkeypatch.setattr(_Settings, "openrouter_api_key", "settings-key", raising=False)
        cfg = _cfg(brain_llm_dedicated=True)  # brain_llm_* all empty
        ctx = _ctx(cfg)
        ctx._init_enricher()
        e = ctx._enricher
        assert e is not None
        assert e._provider_name == "openrouter"  # settings fallback
        assert e._model == "openai/gpt-4o-mini"
        assert e._base_url == "https://openrouter.ai/api/v1"
        assert e._api_key == "settings-key"

    def test_chat_key_fallback_when_provider_matches(self):
        """ON: chat api_key is the final fallback ONLY when providers match."""
        cfg = _cfg(
            brain_llm_dedicated=True,
            brain_llm_provider="anthropic",  # == chat provider
        )
        ctx = _ctx(cfg)
        ctx._init_enricher()
        assert ctx._enricher is not None
        assert ctx._enricher._api_key == "chat-key"

    def test_no_chat_key_fallback_when_provider_mismatches(self, caplog, monkeypatch):
        """ON: provider mismatch + no key → enricher=None + debug log."""
        from unittest.mock import patch

        cfg = _cfg(
            brain_llm_dedicated=True,
            brain_llm_provider="google",  # != chat provider (anthropic)
        )
        ctx = _ctx(cfg)
        with (
            caplog.at_level(logging.DEBUG),
            patch("nous.config.runtime_config.RuntimeConfigManager") as rcm,
        ):
            rcm.return_value.get_effective_value.return_value = ("", None)
            ctx._init_enricher()
        assert ctx._enricher is None
        assert any("no api_key" in r.message for r in caplog.records)


def test_introspection_enabled_default_true():
    cfg = ChatConfig()
    assert cfg.brain_introspection_enabled is True


def test_introspection_config_persisted(tmp_path):
    from nous.domain.chat_config import ChatConfigFileRepository

    repo = ChatConfigFileRepository(str(tmp_path))
    cfg = repo.get("p1")
    cfg.brain_introspection_enabled = False
    repo.save(cfg)
    assert repo.get("p1").brain_introspection_enabled is False


class TestIntrospectionEngineWiring:
    def test_engine_none_when_resolution_fails(self):
        """解決失敗（api_key 無し）→ introspection_engine None。"""
        ctx = _ctx(_cfg(brain_llm_dedicated=True, brain_llm_provider="google"))
        ctx._init_enricher()
        assert ctx._enricher is None
        assert ctx.introspection_engine is None

    def test_reload_rebuilds_engine(self):
        """reload_enricher() で introspection_engine も再構築される。"""
        ctx = _ctx(_cfg())
        ctx._init_enricher()
        first = ctx.introspection_engine
        assert first is not None

        ctx._config.session_config.brain_llm_dedicated = True
        ctx._config.session_config.brain_llm_provider = "anthropic"
        ctx._config.session_config.brain_llm_api_key = "anthropic-key"
        ctx.reload_enricher()
        second = ctx.introspection_engine
        assert second is not None
        assert second is not first


class TestReloadEnricher:
    def test_reload_enricher_swaps_enricher(self):
        """reload_enricher() re-runs the resolution chain with current config."""
        ctx = _ctx(_cfg())  # OFF → chat 4-piece
        ctx._enricher = None
        ctx.reload_enricher()
        first = ctx._enricher
        assert first is not None
        assert first._provider_name == "anthropic"

        # flip to dedicated
        ctx._config.session_config.brain_llm_dedicated = True
        ctx._config.session_config.brain_llm_api_key = "brain-key"
        ctx._config.session_config.brain_llm_provider = "openai"
        ctx.reload_enricher()
        second = ctx._enricher
        assert second is not None
        assert second is not first
        assert second._provider_name == "openai"
        assert second._api_key == "brain-key"


class TestBrainReasoningKeys:
    def test_default_none_medium(self):
        cfg = ChatConfig()
        assert cfg.brain_reasoning_enabled is None  # None = 解決済みLLM設定に従う
        assert cfg.brain_reasoning_effort == "medium"

    def test_effort_clamped(self):
        from nous.domain.session_config import SessionConfig

        assert SessionConfig(brain_reasoning_effort="bogus").brain_reasoning_effort == "medium"

    def test_config_roundtrip(self, tmp_path):
        from nous.domain.chat_config import ChatConfigFileRepository

        repo = ChatConfigFileRepository(str(tmp_path))
        cfg = repo.get("p1")
        cfg.brain_reasoning_enabled = True
        cfg.brain_reasoning_effort = "high"
        repo.save(cfg)
        got = repo.get("p1")
        assert got.brain_reasoning_enabled is True
        assert got.brain_reasoning_effort == "high"


class TestBrainReasoningWiring:
    def test_wiring_passes_effort_to_enricher_and_engine(self):
        ctx = _ctx(_cfg(brain_reasoning_enabled=True, brain_reasoning_effort="high"))
        ctx._init_enricher()
        assert ctx._enricher is not None
        assert ctx._enricher._reasoning_effort == "high"
        assert ctx.introspection_engine is not None
        assert ctx.introspection_engine._reasoning_effort == "high"

    def test_disabled_passes_none(self):
        ctx = _ctx(_cfg())
        ctx._init_enricher()
        assert ctx._enricher is not None
        assert ctx._enricher._reasoning_effort is None
        assert ctx.introspection_engine is not None
        assert ctx.introspection_engine._reasoning_effort is None

    def test_cfg_none_passes_none(self):
        ctx = _ctx(None)
        ctx._init_enricher()
        assert ctx._enricher is not None
        assert ctx._enricher._reasoning_effort is None


class TestBrainMaxTokensKeys:
    def test_default_0_inherit(self):
        cfg = ChatConfig()
        assert cfg.brain_max_tokens == 0  # 0 = 継承センチネル

    def test_clamped_256_to_32768(self):
        from nous.domain.session_config import SessionConfig

        assert SessionConfig(brain_max_tokens=100).brain_max_tokens == 256
        assert SessionConfig(brain_max_tokens=40000).brain_max_tokens == 32768

    def test_config_roundtrip(self, tmp_path):
        from nous.domain.chat_config import ChatConfigFileRepository

        repo = ChatConfigFileRepository(str(tmp_path))
        cfg = repo.get("p1")
        cfg.brain_max_tokens = 4096
        repo.save(cfg)
        assert repo.get("p1").brain_max_tokens == 4096


class TestBrainMaxTokensReasoningLift:
    """reasoning ON 時の自動嵩上げ: max(max_tokens, max(4096, budget+1024))。"""

    def _session(self, **kw):
        from nous.domain.session_config import SessionConfig

        return SessionConfig(**kw)

    def test_on_2048_medium_lifts_to_5120(self):
        assert (
            self._session(
                brain_max_tokens=2048, brain_reasoning_enabled=True, brain_reasoning_effort="medium"
            ).brain_max_tokens
            == 5120
        )

    def test_on_2048_high_lifts_to_9216(self):
        assert (
            self._session(
                brain_max_tokens=2048, brain_reasoning_enabled=True, brain_reasoning_effort="high"
            ).brain_max_tokens
            == 9216
        )

    def test_on_2048_low_lifts_to_4096(self):
        assert (
            self._session(
                brain_max_tokens=2048, brain_reasoning_enabled=True, brain_reasoning_effort="low"
            ).brain_max_tokens
            == 4096
        )

    def test_on_2048_max_lifts_to_17408(self):
        assert (
            self._session(
                brain_max_tokens=2048, brain_reasoning_enabled=True, brain_reasoning_effort="max"
            ).brain_max_tokens
            == 17408
        )

    def test_off_2048_unchanged(self):
        assert self._session(brain_max_tokens=2048, brain_reasoning_enabled=False).brain_max_tokens == 2048

    def test_zero_0_sentinel_raw_storage_runtime_floor(self):
        # 新契約: 0 = 継承センチネル。SessionConfig（保存層）は clamp も嵩上げもせず
        # 生の 0 を保つ（保存値は生のまま）一方、実行時の resolver が reasoning 有効なら
        # floor を適用する（専用LLM ON × brain_max_tokens=0 × reasoning ON → floor）。
        assert self._session(brain_max_tokens=0).brain_max_tokens == 0
        assert (
            self._session(
                brain_max_tokens=0, brain_reasoning_enabled=True, brain_reasoning_effort="max"
            ).brain_max_tokens
            == 0
        )
        # 実行時: reasoning ON → floor 適用（medium 5120 / max 17408）
        from nous.application.chat.introspection import _resolve_brain_llm_params

        p = _resolve_brain_llm_params(
            _rich_cfg(
                brain_llm_dedicated=True,
                brain_max_tokens=0,
                brain_reasoning_enabled=True,
                brain_reasoning_effort="medium",
            )
        )
        assert p.max_tokens == 5120
        p = _resolve_brain_llm_params(
            _rich_cfg(
                brain_llm_dedicated=True,
                brain_max_tokens=0,
                brain_reasoning_enabled=True,
                brain_reasoning_effort="max",
            )
        )
        assert p.max_tokens == 17408
        # 実行時: reasoning OFF/None の 0 は素通し（floor なし）
        p = _resolve_brain_llm_params(
            _rich_cfg(brain_llm_dedicated=True, brain_max_tokens=0, brain_reasoning_enabled=False)
        )
        assert p.max_tokens is None
        p = _resolve_brain_llm_params(_rich_cfg(brain_llm_dedicated=True, brain_max_tokens=0))
        assert p.max_tokens is None

    def test_reasoning_none_not_lifted(self):
        # brain_reasoning_enabled=None（継承）は嵩上げ対象外
        assert (
            self._session(
                brain_max_tokens=2048, brain_reasoning_enabled=None, brain_reasoning_effort="max"
            ).brain_max_tokens
            == 2048
        )

    def test_reasoning_true_explicit_4096_lifted(self):
        # 明示 True + 明示 4096 は medium floor 5120 に嵩上げ
        assert (
            self._session(
                brain_max_tokens=4096, brain_reasoning_enabled=True, brain_reasoning_effort="medium"
            ).brain_max_tokens
            == 5120
        )

    def test_on_explicit_large_unchanged(self):
        # 明示 8192 は引き下げない
        assert (
            self._session(
                brain_max_tokens=8192, brain_reasoning_enabled=True, brain_reasoning_effort="medium"
            ).brain_max_tokens
            == 8192
        )

    def test_on_100_clamped_then_lifted(self):
        # 既存 clamp(256) の後に floor 適用
        assert (
            self._session(
                brain_max_tokens=100, brain_reasoning_enabled=True, brain_reasoning_effort="medium"
            ).brain_max_tokens
            == 5120
        )


class TestBrainMaxTokensWiring:
    """brain_max_tokens は両者共通の上限値。

    - cfg あり → enricher / introspection ともに cfg.brain_max_tokens（デフォルト 4096 含む）
    - cfg なし → 各 ctor デフォルト（enricher 512 / introspection 4096）を維持
    - reasoning ON 時は SessionConfig の model_validator が嵩上げし、resolver
      （_resolve_brain_llm_params）も同一式で floor を適用するため、
      ここで渡す値は「下限」の意味。openai_compat の非Anthropic互換経路も resolver 経由で守られる。
    """

    def test_cfg_present_passes_explicit_value_to_both(self):
        ctx = _ctx(_cfg(brain_max_tokens=4096))
        ctx._init_enricher()
        assert ctx._enricher is not None
        assert ctx._enricher._max_tokens == 4096
        assert ctx.introspection_engine is not None
        assert ctx.introspection_engine._max_tokens == 4096

    def test_cfg_present_default_inherits_chat(self):
        """cfg あり・明示なし（brain_max_tokens=0）→ 会話用 provider_config に従う。"""
        ctx = _ctx(_cfg())
        ctx._init_enricher()
        assert ctx._enricher is not None
        assert ctx._enricher._max_tokens == 8192  # ProviderConfig.max_tokens 既定
        assert ctx.introspection_engine is not None
        assert ctx.introspection_engine._max_tokens == 8192

    def test_cfg_none_uses_ctor_defaults(self):
        ctx = _ctx(None)
        ctx._init_enricher()
        assert ctx._enricher is not None
        assert ctx._enricher._max_tokens == 512
        assert ctx.introspection_engine is not None
        assert ctx.introspection_engine._max_tokens == 4096


def _rich_provider_config() -> ProviderConfig:
    """resolver テスト用: max_tokens 8192 / temperature 0.9 / reasoning ON high。"""
    return ProviderConfig(
        provider="anthropic",
        model="chat-model",
        api_key="chat-key",
        base_url="https://chat.url/v1",
        max_tokens=8192,
        temperature=0.9,
        reasoning_enabled=True,
        reasoning_effort="high",
    )


def _rich_cfg(**session_overrides) -> ChatConfig:
    data = {"memory_enrichment_enabled": True, "provider_config": _rich_provider_config()}
    data.update(session_overrides)
    return ChatConfig(**data)


class TestBrainLLMParamsResolver:
    """_resolve_brain_llm_params（脳側LLMパラメータの単一解決点）。

    None は「呼び出し先の既定を使え」の意味。
    """

    def test_cfg_none_all_none(self):
        p = _resolve_brain_llm_params(None)
        assert p.max_tokens is None and p.temperature is None and p.reasoning_effort is None

    def test_dedicated_off_inherits_chat(self):
        # chat reasoning ON (high) → reasoning floor（9216）が適用される（resolver 集約）
        p = _resolve_brain_llm_params(_rich_cfg())
        assert p.max_tokens == 9216
        assert p.temperature == 0.9
        assert p.reasoning_effort == "high"

    def test_dedicated_off_chat_reasoning_off_effort_none(self):
        cfg = _rich_cfg()
        cfg.provider_config.reasoning_enabled = False
        assert _resolve_brain_llm_params(cfg).reasoning_effort is None

    def test_dedicated_on_unspecified_all_none(self):
        """ON（脳専用LLM）+ brain_* 未設定 → 呼び出し先既定（全 None）。"""
        cfg = _rich_cfg(brain_llm_dedicated=True)
        p = _resolve_brain_llm_params(cfg)
        assert p.max_tokens is None and p.temperature is None and p.reasoning_effort is None

    def test_explicit_max_tokens_overrides_only_tokens(self):
        # 明示 2048 は上書きする。ただし reasoning ON (high) なら floor 9216 まで嵩上げ
        cfg = _rich_cfg(brain_max_tokens=2048)
        p = _resolve_brain_llm_params(cfg)
        assert p.max_tokens == 9216
        assert p.temperature == 0.9
        assert p.reasoning_effort == "high"

    def test_temperature_zero_preserved(self):
        """会話側の明示 temperature=0.0 が 0.7 に化けない（falsy チェック除去の検証）。"""
        cfg = _rich_cfg()
        cfg.provider_config.temperature = 0.0
        p = _resolve_brain_llm_params(cfg)
        assert p.temperature == 0.0

    def test_brain_reasoning_true_forces_effort_even_off_mode(self):
        cfg = _rich_cfg(brain_reasoning_enabled=True, brain_reasoning_effort="medium")
        assert _resolve_brain_llm_params(cfg).reasoning_effort == "medium"

    def test_brain_reasoning_false_wins_over_chat_reasoning(self):
        cfg = _rich_cfg(brain_reasoning_enabled=False)  # chat reasoning は ON (high)
        assert _resolve_brain_llm_params(cfg).reasoning_effort is None

    def test_temperature_wiring_off_mode(self):
        """OFF モードで会話用 temperature が enricher / introspection の双方に渡る。"""
        ctx = _ctx(_cfg())
        ctx._init_enricher()
        assert ctx._enricher is not None
        assert ctx._enricher._temperature == 0.7
        assert ctx.introspection_engine is not None
        assert ctx.introspection_engine._temperature == 0.7

    def test_temperature_wiring_cfg_none_uses_ctor_defaults(self):
        ctx = _ctx(None)
        ctx._init_enricher()
        assert ctx._enricher is not None
        assert ctx._enricher._temperature == 0.3
        assert ctx.introspection_engine is not None
        assert ctx.introspection_engine._temperature == 0.7


class TestBrainSpontaneousKeys:
    def test_default_on_1h(self):
        cfg = ChatConfig()
        assert cfg.brain_spontaneous_enabled is True
        assert cfg.brain_spontaneous_interval_hours == 1

    def test_interval_clamped_1_to_72(self):
        from nous.domain.session_config import SessionConfig

        assert SessionConfig(brain_spontaneous_interval_hours=0).brain_spontaneous_interval_hours == 1
        assert SessionConfig(brain_spontaneous_interval_hours=100).brain_spontaneous_interval_hours == 72

    def test_config_roundtrip(self, tmp_path):
        from nous.domain.chat_config import ChatConfigFileRepository

        repo = ChatConfigFileRepository(str(tmp_path))
        cfg = repo.get("p1")
        cfg.brain_spontaneous_enabled = True
        cfg.brain_spontaneous_interval_hours = 12
        repo.save(cfg)
        got = repo.get("p1")
        assert got.brain_spontaneous_enabled is True
        assert got.brain_spontaneous_interval_hours == 12


class TestBrainSessionIdWiring:
    """脳側の Go セッションID: persona ベースで安定 (nous-brain-<persona>)。"""

    def test_brain_providers_get_persona_session(self):
        ctx = _ctx(_cfg())
        ctx.persona = "herta"
        ctx._init_enricher()
        assert ctx._enricher is not None
        assert ctx._enricher._session_id == "nous-brain-herta"
        assert ctx.introspection_engine is not None
        assert ctx.introspection_engine._session_id == "nous-brain-herta"

    def test_no_persona_falls_back_to_none(self):
        ctx = _ctx(_cfg())  # persona 未設定 (空文字)
        ctx._init_enricher()
        assert ctx._enricher is not None
        assert ctx._enricher._session_id is None
