"""Unit tests for the periodic ReflectionEngine (system-message build)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from nous.application.chat.reflection import ReflectionEngine
from nous.domain.memory.entities import Memory


class TestBuildSystemMessageRelativeTime:
    """ReflectionEngine._build_system_message の記憶行に相対時刻が付く。"""

    def test_memory_lines_include_relative_time(self):
        now = datetime.now(UTC)
        memories = [
            Memory(
                key="k1",
                content="recent event",
                created_at=now - timedelta(hours=1),
                updated_at=now - timedelta(hours=1),
            ),
            Memory(
                key="k2",
                content="old fact",
                created_at=now - timedelta(days=366),
                updated_at=now - timedelta(days=366),
            ),
        ]
        msg = ReflectionEngine()._build_system_message("test_persona", memories)
        assert "recent event (1h ago)" in msg
        assert "old fact (1y ago)" in msg
        # プロンプト指示行（古い記憶と直近の出来事を混同しない）も追加されている
        assert "混同しないこと" in msg
