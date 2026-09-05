"""Task 5: HF snapshot revision pinning is env-configurable (supply-chain)."""

from __future__ import annotations

from nous.infrastructure.embedding._base import _hf_revision


def test_revision_unset_means_latest(monkeypatch):
    monkeypatch.delenv("NOUS_EMBEDDING__REVISION", raising=False)
    assert _hf_revision("NOUS_EMBEDDING__REVISION") is None


def test_revision_read_from_env(monkeypatch):
    monkeypatch.setenv("NOUS_EMBEDDING__REVISION", "abc123")
    assert _hf_revision("NOUS_EMBEDDING__REVISION") == "abc123"
