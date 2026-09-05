"""tests/unit/test_voice_emotion_mode.py"""

from nous.domain.chat_config import ChatConfig
from nous.domain.session_config import SessionConfig


def test_default_is_anchor():
    assert SessionConfig().voice_emotion_mode == "anchor"


def test_legacy_link_off_derives_off():
    assert SessionConfig(voice_emotion_link=False).voice_emotion_mode == "off"


def test_legacy_llm_enabled_derives_llm():
    assert SessionConfig(irodori_caption_llm_enabled=True).voice_emotion_mode == "llm"


def test_legacy_dead_combo_derives_off():
    # link OFF + llm ON は旧実装では無音 (state なしで LLM 到達不能)。
    # 実際に聞こえていた通り "off" に倒す。
    cfg = SessionConfig(voice_emotion_link=False, irodori_caption_llm_enabled=True)
    assert cfg.voice_emotion_mode == "off"


def test_explicit_mode_wins_over_legacy():
    cfg = SessionConfig(
        voice_emotion_mode="llm",
        voice_emotion_link=False,
        irodori_caption_llm_enabled=False,
    )
    assert cfg.voice_emotion_mode == "llm"


def test_invalid_mode_falls_back_to_anchor():
    assert SessionConfig(voice_emotion_mode="turbo").voice_emotion_mode == "anchor"


def test_chat_config_flat_distribution():
    cfg = ChatConfig(voice_emotion_mode="llm")
    assert cfg.voice_emotion_mode == "llm"


def test_chat_config_legacy_flat_derives_mode():
    cfg = ChatConfig(voice_emotion_link=False)
    assert cfg.voice_emotion_mode == "off"
