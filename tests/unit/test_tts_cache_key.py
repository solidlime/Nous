"""TTS キャッシュキーの単体テスト — voice_override 差分でキャッシュヒントが変わること。"""

import pytest

from nous.api.http.routers import tts as tts_mod
from nous.api.http.routers.tts import _find_cache_file, _tts_cache_key

pytestmark = pytest.mark.unit


def _key(voice: str | None) -> str:
    return _tts_cache_key(
        text="こんにちは",
        emotion="neutral",
        caption=None,
        voice_speed=1.0,
        voice_override=voice,
    )


def test_voice_override_changes_cache_key():
    """声が違えばキャッシュキーも違う（旧声の音声を返さない）"""
    assert _key("voice_a") != _key("voice_b")


def test_none_and_missing_voice_share_key():
    """voice_override None と空文字は同一キー（後方互換）"""
    assert _key(None) == _key("")


def test_same_voice_same_key():
    assert _key("voice_a") == _key("voice_a")


def test_full_hash_filename_and_resolved_voice():
    from nous.api.http.routers.tts import _tts_cache_key
    k1 = _tts_cache_key(text="a", emotion="neutral", caption=None, voice_speed=1.0, voice_override=None, voice_resolved="v1", model="irodori-tts", seed=0, num_steps=30, cfg_text=3.2, cfg_speaker=5.0, cfg_caption=4.2, chunk_min_chars=85)
    k2 = _tts_cache_key(text="a", emotion="neutral", caption=None, voice_speed=1.0, voice_override=None, voice_resolved="v2", model="irodori-tts", seed=0, num_steps=30, cfg_text=3.2, cfg_speaker=5.0, cfg_caption=4.2, chunk_min_chars=85)
    assert len(k1) == 64
    assert k1 != k2


def test_find_cache_exact_hit(tmp_path):
    key = "a" * 64
    p = tmp_path / f"{key}.wav"
    p.write_bytes(b"RIFF....")
    found, name = _find_cache_file(tmp_path, key)
    assert found == p and name == p.name


def test_find_cache_miss_empty(tmp_path):
    found, name = _find_cache_file(tmp_path, "b" * 64)
    assert found is None and name == "b" * 64 + ".wav"


def test_legacy_prefix_only_is_miss(tmp_path):
    key = "c" * 64
    (tmp_path / f"{key[:12]}xxxx.wav").write_bytes(b"RIFF....")
    found, name = _find_cache_file(tmp_path, key)
    assert found is None and name == f"{key}.wav"


def test_synthesize_lookup_uses_full_stem_match():
    import inspect

    src = inspect.getsource(tts_mod.register_tts_routes)
    assert "_find_cache_file(cache_dir, cache_key)" in src


def test_cache_key_version_breaks_old_entries():
    """v2接頭辞: 旧形式（接頭辞なし）材料のハッシュと一致しない＝腐ったHITを返さない。"""
    import hashlib
    import json

    new_key = _tts_cache_key(
        text="a",
        emotion="neutral",
        caption=None,
        voice_speed=1.0,
        voice_override=None,
    )
    old_material = json.dumps(
        ["a", "neutral", "", 1.0, "", "", "irodori-tts", 0, 30, 3.2, 5.0, 4.2, 85],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    old_key = hashlib.sha256(old_material.encode()).hexdigest()
    assert len(new_key) == 64
    assert new_key != old_key
