"""B-2: BlockRepository の persona 対応 + profile block API."""

from __future__ import annotations

import pytest

from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository


@pytest.fixture
def repo(tmp_path):
    conn = SQLiteConnection(data_dir=str(tmp_path), persona="test")
    conn.initialize_schema()
    return SQLiteMemoryRepository(conn)


class TestPersonaBlocks:
    def test_default_persona_backward_compat(self, repo):
        assert repo.save_block("b1", "c1").is_ok
        row = repo.get_block("b1").value
        assert row["content"] == "c1"
        assert row["persona"] == "default"

    def test_personas_are_isolated(self, repo):
        repo.save_block("shared", "default-content")
        repo.save_block("shared", "other-content", persona="other")
        assert repo.get_block("shared").value["content"] == "default-content"
        assert repo.get_block("shared", "other").value["content"] == "other-content"
        assert len(repo.list_blocks().value) == 1
        assert len(repo.list_blocks("other").value) == 1

    def test_delete_is_persona_scoped(self, repo):
        repo.save_block("x", "a")
        repo.save_block("x", "b", persona="other")
        repo.delete_block("x", "other")
        assert repo.get_block("x", "other").value is None
        assert repo.get_block("x").value is not None


class TestProfileBlocks:
    def test_get_profile_blocks_empty(self, repo):
        assert repo.get_profile_blocks().value == {}

    def test_upsert_creates_and_rewrites(self, repo):
        assert repo.upsert_profile_block("p1", "me", "初稿").is_ok
        assert repo.upsert_profile_block("p1", "me", "改稿").is_ok
        blocks = repo.get_profile_blocks("p1").value
        assert set(blocks) == {"me"}
        assert blocks["me"]["content"] == "改稿"
        assert blocks["me"]["block_type"] == "profile"
        # 全体リライト型: 行は増えない
        assert len(repo.list_blocks("p1").value) == 1

    def test_get_profile_blocks_excludes_custom(self, repo):
        repo.save_block("custom_block", "x", persona="p1")
        repo.upsert_profile_block("p1", "user", "ユーザー像")
        assert set(repo.get_profile_blocks("p1").value) == {"user"}

    def test_get_profile_blocks_persona_scoped(self, repo):
        repo.upsert_profile_block("p1", "me", "p1の自己像")
        repo.upsert_profile_block("p2", "me", "p2の自己像")
        assert repo.get_profile_blocks("p1").value["me"]["content"] == "p1の自己像"
        assert repo.get_profile_blocks("p2").value["me"]["content"] == "p2の自己像"

    def test_upsert_rejects_unknown_name(self, repo):
        result = repo.upsert_profile_block("p1", "hack", "x")
        assert not result.is_ok
        assert repo.get_profile_blocks("p1").value == {}
