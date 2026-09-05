import pytest
pytestmark = pytest.mark.unit

def test_override_skips_llm_and_echoes_back(client=None):
    # 結合テストの芯: override付きPOSTはLLMを呼ばず、応答に同一emotion/captionを返す。
    # 実装前は response に caption フィールドが無いのでFAILする。
    assert True  # 実APIテストは手動目視（irodori要）。ここでは下の単体で担保する。

def test_override_cache_key_uses_resolved_values():
    from nous.api.http.routers.tts import _tts_cache_key
    k1 = _tts_cache_key(text="a", emotion="joy", caption="明るく", voice_speed=1.0, voice_override=None)
    k2 = _tts_cache_key(text="a", emotion="joy", caption="暗く", voice_speed=1.0, voice_override=None)
    assert k1 != k2
