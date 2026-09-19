"""Tests for Sudachi-based FTS tokenization (morpheme-level Japanese FTS).

Hermetic: the Sudachi tokenizer is replaced by a deterministic fake
(char-split for CJK runs) so tests never depend on the 207MB dictionary.
The real-dictionary path is verified live (docs/reviews/2026-09-19 §8).
"""

from __future__ import annotations

import re

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite import fts_tokenize
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository
from nous.infrastructure.sqlite.migrations import run_migrations

PERSONA = "test_fts_sudachi"


def _fake_tokenize(text: str) -> str:
    """Deterministic fake: split CJK runs into single chars, keep latin runs."""
    parts: list[str] = []
    for run in re.findall(r"[^\s]+", text):
        buf = ""
        prev_cjk = False
        for ch in run:
            cjk = "\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff"
            if cjk:
                if buf and not prev_cjk:
                    parts.append(buf)
                    buf = ""
                parts.append(ch)
                prev_cjk = True
            else:
                if prev_cjk:
                    prev_cjk = False
                buf += ch
        if buf:
            parts.append(buf)
    return " ".join(parts)


@pytest.fixture()
def fake_sudachi(monkeypatch):
    monkeypatch.setattr(fts_tokenize, "_get_tokenizer", lambda: object())
    monkeypatch.setattr(fts_tokenize, "tokenize_for_fts", _fake_tokenize)


@pytest.fixture()
def repo(tmp_path, fake_sudachi):
    conn = SQLiteConnection(data_dir=str(tmp_path), persona=PERSONA)
    conn.initialize_schema()
    try:
        yield SQLiteMemoryRepository(conn)
    finally:
        conn.close()


def _mem(key: str, content: str) -> Memory:
    now = get_now()
    return Memory(key=key, content=content, created_at=now, updated_at=now)


class TestFTSMorphemeSearch:
    def test_morpheme_query_matches_saved_memory(self, repo):
        """CJK 連結クエリ（助詞なし）でも Sudachi 形態素で一致する。"""
        repo.save(_mem("m1", "itestは量子テレポーテーションの実験に成功した"))

        result = repo.search_fts("量子テレポーテーション実験", top_k=5)
        assert result.is_ok
        keys = [m.key for m, _ in result.value]
        assert keys == ["m1"]

    def test_update_retokenizes_index(self, repo):
        """content 更新時に FTS 行も再トークン化される。"""
        repo.save(_mem("m2", "古い内容についての記憶"))
        repo.update("m2", content="珊瑚礁の白化現象を調査した")

        new_hit = [m.key for m, _ in repo.search_fts("珊瑚礁 白化", top_k=5).value]
        old_hit = [m.key for m, _ in repo.search_fts("古い内容", top_k=5).value]
        assert new_hit == ["m2"]
        assert old_hit == []

    def test_query_sanitizer_segments_terms(self, repo, fake_sudachi):
        """_sanitize_fts_query がトークン単位の AND に展開する。"""
        q = SQLiteMemoryRepository._sanitize_fts_query("量子テレポーテーション実験")
        assert (
            q
            == '"量" AND "子" AND "テ" AND "レ" AND "ポ" AND "ー" AND "テ" AND "ー" AND "シ" AND "ョ" AND "ン" AND "実" AND "験"'
        )

    def test_fallback_keeps_raw_terms_without_tokenizer(self, repo, monkeypatch):
        """トークナイザー無しでは従来通りの引用 AND を返す（劣化フォールバック）。"""
        monkeypatch.setattr(fts_tokenize, "_get_tokenizer", lambda: None)
        repo.save(_mem("m3", "plain ascii content"))
        hit = [m.key for m, _ in repo.search_fts("ascii content", top_k=5).value]
        assert hit == ["m3"]


class TestTokenizeFallback:
    def test_tokenize_for_fts_returns_input_when_load_fails(self, monkeypatch):
        monkeypatch.setattr(fts_tokenize, "_tokenizer", None)
        monkeypatch.setattr(fts_tokenize, "_load_failed", True)
        assert fts_tokenize.tokenize_for_fts("そのまま返す") == "そのまま返す"


class TestMigrationV10Retokenize:
    def test_v10_retokenizes_existing_raw_rows(self, tmp_path, fake_sudachi):
        """既存 DB の raw FTS 行が v10 マイグレーションで再トークン化される。"""
        conn = SQLiteConnection(data_dir=str(tmp_path), persona=PERSONA)
        conn.initialize_schema()
        db = conn.get_memory_db()
        try:
            # まず 1 件保存（fake トークナイザで FTS 行が作られる）
            repo = SQLiteMemoryRepository(conn)
            now = get_now()
            repo.save(Memory(key="m10", content="珊瑚礁の白化現象", created_at=now, updated_at=now))
            # v9 適用済みの状態を作り、FTS 行を raw のまま差し戻す
            db.execute("DELETE FROM memories_fts")
            db.execute(
                "INSERT INTO memories_fts(rowid, content, memories_key) SELECT rowid, content, key FROM memories"
            )
            db.execute("DELETE FROM _migration_version WHERE version >= 10")
            db.commit()

            run_migrations(db, PERSONA)

            rows = db.execute("SELECT content FROM memories_fts").fetchall()
            assert rows, "FTS rows must survive the migration"
            for row in rows:
                assert " " in row["content"], "row must be re-tokenized (space-separated)"
        finally:
            conn.close()
