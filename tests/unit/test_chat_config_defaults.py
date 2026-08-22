"""Tests for ChatConfigRepository._infer_default_value (pydantic default 優先)."""

from __future__ import annotations

from nous.domain.chat_config import ChatConfig, ChatConfigRepository


def test_infer_default_value_uses_pydantic_default():
    f = ChatConfig._all_flat_fields()
    # int 既定値がそのまま入る（旧実装だと "0"）
    assert ChatConfigRepository._infer_default_value(f["memory_digest_count"]) == "5"
    # bool True 既定（旧実装だと "0"）
    assert ChatConfigRepository._infer_default_value(f["context_compress_system_prompt"]) == "1"
    # str 既定
    assert ChatConfigRepository._infer_default_value(f["system_prompt"]) == "''"
