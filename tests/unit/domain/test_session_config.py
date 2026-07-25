"""Tests for SessionConfig model."""

from __future__ import annotations

from nous.domain.session_config import SessionConfig


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
