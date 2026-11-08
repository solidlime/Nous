from nous.domain.session_config import SessionConfig


def test_h_spec_defaults():
    cfg = SessionConfig()
    assert cfg.brain_llm_dedicated is False
