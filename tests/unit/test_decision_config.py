"""Tests for brain_decision_* config keys, resolver, and tier classification (#011)."""

from __future__ import annotations

from nous.api.http.routers.chat.chat_management import _field_section, _field_tier
from nous.domain.chat_config import ChatConfig, ChatConfigFileRepository
from nous.domain.memory.query_service import resolve_decision_config


def _repo(tmp_path, **cfg_kwargs):
    repo = ChatConfigFileRepository(str(tmp_path))
    repo.save(ChatConfig(persona="p", **cfg_kwargs))

    class _Conn:
        data_dir = str(tmp_path)
        persona = "p"

    class _Repo:
        _conn = _Conn()

    return _Repo()


def test_round_trip(tmp_path):
    repo = ChatConfigFileRepository(str(tmp_path))
    repo.save(
        ChatConfig(
            persona="p",
            brain_decision_enabled=True,
            brain_decision_model="gpt-x",
            brain_decision_threshold=0.7,
            brain_decision_max_hops=3,
        )
    )
    loaded = repo.get("p")
    assert loaded.brain_decision_enabled is True
    assert loaded.brain_decision_model == "gpt-x"
    assert loaded.brain_decision_threshold == 0.7
    assert loaded.brain_decision_max_hops == 3


def test_defaults():
    cfg = ChatConfig(persona="p")
    assert cfg.brain_decision_enabled is False
    assert cfg.brain_decision_model == ""
    assert cfg.brain_decision_threshold == 0.55
    assert cfg.brain_decision_max_hops == 1


def test_clamp_validators():
    cfg = ChatConfig(persona="p", brain_decision_threshold=2.0, brain_decision_max_hops=99)
    assert cfg.brain_decision_threshold == 1.0
    assert cfg.brain_decision_max_hops == 5
    cfg2 = ChatConfig(persona="p", brain_decision_threshold=-1.0, brain_decision_max_hops=0)
    assert cfg2.brain_decision_threshold == 0.0
    assert cfg2.brain_decision_max_hops == 1


def test_resolve_defaults_without_conn():
    assert resolve_decision_config(object()) == {"enabled": False, "model": "", "threshold": 0.55, "max_hops": 1}


def test_resolve_reads_config(tmp_path):
    repo = _repo(
        tmp_path,
        brain_decision_enabled=True,
        brain_decision_model="m",
        brain_decision_threshold=0.8,
        brain_decision_max_hops=4,
    )
    assert resolve_decision_config(repo) == {"enabled": True, "model": "m", "threshold": 0.8, "max_hops": 4}


def test_tier_and_section():
    for key in (
        "brain_decision_enabled",
        "brain_decision_model",
        "brain_decision_threshold",
        "brain_decision_max_hops",
    ):
        assert _field_tier(key) == "advanced"
        assert _field_section(key) == "brain_simulation"
