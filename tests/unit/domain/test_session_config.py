"""Tests for SessionConfig model."""

from __future__ import annotations

from nous.domain.session_config import AvatarConfig, SessionConfig


class TestSessionConfig:
    """SessionConfig field defaults."""

    def test_show_message_timestamps_defaults_to_false(self):
        """show_message_timestamps should default to False."""
        cfg = SessionConfig()
        assert cfg.show_message_timestamps is False

    def test_show_message_timestamps_can_be_set_to_true(self):
        """show_message_timestamps should be settable to True."""
        cfg = SessionConfig(show_message_timestamps=True)
        assert cfg.show_message_timestamps is True


class TestAvatarConfig:
    """AvatarConfig defaults (R6) — 既定は無効で後方互換を保つ."""

    def test_defaults_disabled(self):
        cfg = AvatarConfig()
        assert cfg.enabled is False
        assert cfg.panel_position == "top"
        assert cfg.mouth_mode == "analyser"
        assert cfg.panel_width == 220

    def test_session_config_has_avatar_default(self):
        cfg = SessionConfig()
        assert isinstance(cfg.avatar, AvatarConfig)
        assert cfg.avatar.enabled is False

    def test_mouth_mode_literals(self):
        assert AvatarConfig(mouth_mode="toggle").mouth_mode == "toggle"
        assert AvatarConfig(panel_position="bottom").panel_position == "bottom"

    def test_panel_width_clamped(self):
        assert AvatarConfig(panel_width=10).panel_width == 80
        assert AvatarConfig(panel_width=5000).panel_width == 800
