"""GET /api/chat/{persona}/config/defaults — モデルから自動取得するデフォルト。"""

from __future__ import annotations

import asyncio
import json

from nous.api.http.routers.chat import chat_management
from nous.api.http.routers.chat.chat_management import _do_get_config_defaults, get_config_defaults


def test_defaults_include_current_values():
    fields = _do_get_config_defaults()["fields"]
    assert fields["brain_spontaneous_interval_hours"]["default"] == 1
    assert fields["forgetting_decay_interval_seconds"]["default"] == 3600
    assert fields["item_llm_dedicated"]["default"] is False
    assert fields["max_tool_calls"]["default"] == 5
    assert fields["temperature"]["default"] == 0.7
    assert fields["temperature"]["type"] == "float"
    assert fields["brain_spontaneous_interval_hours"]["type"] == "int"
    assert fields["api_key"]["type"] == "str"  # Optional[str] は str に正規化
    assert fields["brain_spontaneous_interval_hours"]["section"] == "brain_simulation"
    assert fields["forgetting_decay_interval_seconds"]["section"] == "forgetting"
    assert fields["voice_streaming"]["default"] is True
    assert fields["voice_streaming"]["section"] == "voice"
    assert fields["voice_streaming"]["type"] == "bool"


def test_undefined_and_meta_keys_excluded():
    fields = _do_get_config_defaults()["fields"]
    for missing in ("not_a_field", "persona", "updated_at"):
        assert missing not in fields


def test_api_keys_are_blank():
    fields = _do_get_config_defaults()["fields"]
    api_keys = [k for k in fields if k == "api_key" or k.endswith("_api_key")]
    assert api_keys  # provider.api_key + brain/item/image_caption
    for k in api_keys:
        assert fields[k]["default"] == "", k


def test_every_field_has_contract_shape():
    fields = _do_get_config_defaults()["fields"]
    assert fields  # non-empty
    for name, meta in fields.items():
        assert set(meta) == {"default", "help", "type", "section"}, name


def test_endpoint_returns_fields(monkeypatch):
    monkeypatch.setattr(chat_management, "_resolve_request", lambda req: ("p", object()))
    resp = asyncio.run(get_config_defaults(object()))
    body = json.loads(resp.body)
    assert body["fields"]["brain_spontaneous_interval_hours"]["default"] == 1
