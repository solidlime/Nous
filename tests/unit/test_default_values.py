from nous.domain.session_config import SessionConfig


def test_h_spec_defaults():
    cfg = SessionConfig()
    assert cfg.brain_monologue_enabled is True
