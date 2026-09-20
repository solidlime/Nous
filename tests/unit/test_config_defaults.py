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
        assert set(meta) == {"default", "help", "type", "section", "tier"}, name
        assert meta["tier"] in {"basic", "advanced", "expert"}, name


def test_endpoint_returns_fields(monkeypatch):
    monkeypatch.setattr(chat_management, "_resolve_request", lambda req: ("p", object()))
    resp = asyncio.run(get_config_defaults(object()))
    body = json.loads(resp.body)
    assert body["fields"]["brain_spontaneous_interval_hours"]["default"] == 1


def test_irodori_chunk_min_chars_is_single_valued():
    """v4.0 (audit L5) — chunk_min_chars は 1 つの値だけを持つ。

    このノブは以前 3 箇所に別々の既定値を持っていた（engine 層の
    ``IrodoriAdvancedParams.chunk_min_chars`` = 40、chat 層の
    ``ChatConfig.irodori_chunk_min_chars`` = 85、``_get_irodori_config`` の
    bare な getattr fallback = 40）。実際の chat TTS は常に chat 層の値を使う
    ため、engine 層と fallback の 40 は「UI には 85 と出るのに実装のどこかでは
    40」という説明不能な差を生んでいた。ここでは両層と fallback が同じ 85 で
    あることを機械的に固定する（値変更時はこのテストが赤くなり、UI 表示・
    session_config ・engine 層を同時に動かすことを強制する）。
    """
    from nous.api.http.routers.tts import _get_irodori_config
    from nous.config.settings import IrodoriAdvancedParams
    from nous.domain.session_config import SessionConfig

    engine_default = IrodoriAdvancedParams.model_fields["chunk_min_chars"].default
    chat_default = SessionConfig.model_fields["irodori_chunk_min_chars"].default
    assert engine_default == chat_default == 85

    # fallback も同じ値でなければならない（chat_config に属性が無い異常時のみ発動）。
    class _Bare:
        voice_url = None
        voice_model = None

    cfg = _get_irodori_config(type("Ctx", (), {"settings": _SettingsStub()})(), _Bare())
    assert cfg.advanced.chunk_min_chars == 85


class _SettingsStub:
    """_get_irodori_config が参照する global settings の最小スタブ。"""

    def __init__(self) -> None:
        from nous.config.settings import IrodoriConfig

        self.irodori = IrodoriConfig(url="http://irodori:8088", voice="kiritan")
