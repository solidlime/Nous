"""Tests for CompressionConfig memory_digest_count / memory_preload_count."""

from __future__ import annotations

from nous.domain.compression_config import CompressionConfig


def test_memory_digest_count_default_and_clamp():
    c = CompressionConfig()
    assert c.memory_digest_count == 5
    assert CompressionConfig(memory_digest_count=-1).memory_digest_count == 0
    assert CompressionConfig(memory_digest_count=99).memory_digest_count == 20


def test_memory_preload_count_default_is_5():
    assert CompressionConfig().memory_preload_count == 5
