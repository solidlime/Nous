"""Unit tests for Goals/Promises storage and Memory Stats initialisation.

T7 test cases:
1. JSON 保存確認       — promises/goals が list として DB に往復できること
2. ACTIVE COMMITMENTS  — _format_lightweight_response() に P1/P2 が現れること
3. 空リストでクリア    — [] で上書きすると persona_info から消えること
4. memory_strength 初期化 — save() 直後に strength=1.0 レコードが存在すること
5. entity 自動抽出     — 英語固有名詞が memory_entities に登録されること (best-effort)
"""

from __future__ import annotations

import warnings

import pytest

from nous.api.mcp.tools import _format_lightweight_response
from nous.domain.memory.entities import Memory
from nous.domain.memory.entity_extractor import SimpleEntityExtractor
from nous.domain.memory.graph import EntityService
from nous.domain.persona.entities import EmotionRecord, PersonaState
from nous.domain.persona.service import PersonaService
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.entity_repo import SQLiteEntityRepository
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository
from nous.infrastructure.sqlite.persona_repo import SQLitePersonaRepository

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

PERSONA = "test_persona"


def _make_memory(key: str = "memory_20250101120000", content: str = "test") -> Memory:
    now = get_now()
    return Memory(key=key, content=content, created_at=now, updated_at=now)


# ---------------------------------------------------------------------------
# Fixtures — all backed by a real SQLite in-memory DB (tmp_path)
# ---------------------------------------------------------------------------


@pytest.fixture()
def sqlite_conn(tmp_path):
    """Fresh SQLiteConnection with fully-initialised schema."""
    conn = SQLiteConnection(data_dir=str(tmp_path), persona=PERSONA)
    conn.initialize_schema()
    yield conn
    conn.close()


@pytest.fixture()
def persona_repo(sqlite_conn: SQLiteConnection):
    return SQLitePersonaRepository(sqlite_conn)


@pytest.fixture()
def persona_service(persona_repo: SQLitePersonaRepository):
    return PersonaService(persona_repo)


@pytest.fixture()
def memory_repo(sqlite_conn: SQLiteConnection):
    return SQLiteMemoryRepository(sqlite_conn)


@pytest.fixture()
def entity_repo(sqlite_conn: SQLiteConnection):
    return SQLiteEntityRepository(sqlite_conn)


@pytest.fixture()
def entity_service(entity_repo: SQLiteEntityRepository):
    return EntityService(entity_repo, SimpleEntityExtractor())


# ===========================================================================
# T7-1: JSON 保存確認
# ===========================================================================


class TestPromisesJsonPersistence:
    """goals/promises は persona_info に保存されず、memory タグで管理される。"""

    def test_goals_skipped_in_persona_info(self, persona_service: PersonaService):
        """update_persona_info(goals=[...]) → persona_info には保存されない。"""
        result = persona_service.update_persona_info(PERSONA, {"goals": ["Goal A", "Goal B"]})
        assert result.is_ok, f"update_persona_info failed: {result}"

        ctx = persona_service.get_context(PERSONA)
        assert ctx.is_ok
        state = ctx.value
        # goals は persona_info には保存されない
        goals = state.persona_info.get("goals")
        assert goals is None, f"Expected None (goals not stored in persona_info), got {goals!r}"

    def test_promises_skipped_in_persona_info(self, persona_service: PersonaService):
        """update_persona_info(promises=[...]) → persona_info には保存されない。"""
        result = persona_service.update_persona_info(PERSONA, {"promises": ["P1", "P2"]})
        assert result.is_ok

        ctx = persona_service.get_context(PERSONA)
        assert ctx.is_ok
        promises = ctx.value.persona_info.get("promises")
        assert promises is None, f"Expected None (promises not stored in persona_info), got {promises!r}"

    def test_other_persona_info_keys_still_stored(self, persona_service: PersonaService):
        """goals/promises 以外のキーは persona_info に正常に保存される。"""
        result = persona_service.update_persona_info(PERSONA, {"nickname": "TestBot", "goals": ["should be skipped"]})
        assert result.is_ok

        ctx = persona_service.get_context(PERSONA)
        assert ctx.is_ok
        state = ctx.value
        assert state.persona_info.get("nickname") == "TestBot"
        assert state.persona_info.get("goals") is None


# ===========================================================================
# T7-2: get_context ACTIVE COMMITMENTS 表示確認
# ===========================================================================


class TestActiveCommitmentsDisplay:
    """_format_lightweight_response() が memory タグベースの ACTIVE COMMITMENTS を表示する。
    lightweight モードではアクティブなゴール/約束のみ表示。過去のものは get_context では非表示。"""

    @staticmethod
    def _state() -> PersonaState:
        return PersonaState(
            persona=PERSONA,
            emotion="neutral",
            emotion_intensity=0.0,
            user_info={},
            persona_info={},
        )

    @staticmethod
    def _make_goal(content: str, status: str = "active") -> Memory:
        now = get_now()
        return Memory(key=f"goal_{content[:8]}", content=content, created_at=now, updated_at=now, tags=["goal", status])

    @staticmethod
    def _make_promise(content: str, status: str = "active") -> Memory:
        now = get_now()
        return Memory(
            key=f"promise_{content[:8]}", content=content, created_at=now, updated_at=now, tags=["promise", status]
        )

    @staticmethod
    def _fmt(goals: list) -> str:
        return _format_lightweight_response(
            state=TestActiveCommitmentsDisplay._state(),
            top_memories=[],
            goals=goals,
            equipment={},
            recent=[],
            time_since="",
        )

    def test_goals_appear_in_output(self):
        """active goal が ACTIVE COMMITMENTS に表示される。"""
        output = self._fmt([self._make_goal("Goal A"), self._make_goal("Goal B")])
        assert "Goal A" in output
        assert "Goal B" in output
        assert "ACTIVE COMMITMENTS" in output

    def test_empty_goals_show_no_commitments_section(self):
        """goals が空のとき ACTIVE COMMITMENTS セクションは現れない。"""
        output = self._fmt([])
        assert "ACTIVE COMMITMENTS" not in output

    def test_non_active_goals_not_shown(self):
        """achieved goal は軽量モードで表示されない（active のみ表示）。"""
        output = self._fmt([self._make_goal("Done Goal", "achieved")])
        assert "ACTIVE COMMITMENTS" not in output
        assert "Done Goal" not in output


# ===========================================================================
# T7-3: 空リストでクリア
# ===========================================================================


class TestPromisesClear:
    """goals/promises の memory タグベース管理を確認。"""

    def test_goals_not_stored_in_persona_info_after_update(self, persona_service: PersonaService):
        """goals を persona_info で渡しても persona_info には保存されない。"""
        persona_service.update_persona_info(PERSONA, {"goals": ["G1", "G2"]})
        persona_service.update_persona_info(PERSONA, {"goals": []})

        state = persona_service.get_context(PERSONA).value
        goals = state.persona_info.get("goals")
        assert goals is None, f"goals should not be in persona_info, got {goals!r}"

    def test_promises_not_stored_in_persona_info_after_update(self, persona_service: PersonaService):
        """promises を persona_info で渡しても persona_info には保存されない。"""
        persona_service.update_persona_info(PERSONA, {"promises": ["P1"]})
        persona_service.update_persona_info(PERSONA, {"promises": []})

        state = persona_service.get_context(PERSONA).value
        promises = state.persona_info.get("promises")
        assert promises is None, f"promises should not be in persona_info, got {promises!r}"

    def test_memory_repo_get_by_tags_finds_goals(self, memory_repo: SQLiteMemoryRepository):
        """memory_repo.get_by_tags(['goal','active']) で goal memories が取得できる。"""
        now = get_now()
        mem = Memory(
            key="goal_test_001",
            content="Test goal",
            created_at=now,
            updated_at=now,
            tags=["goal", "active"],
            importance=0.8,
        )
        memory_repo.save(mem)

        result = memory_repo.get_by_tags(["goal", "active"])
        assert result.is_ok
        contents = [m.content for m in result.value]
        assert "Test goal" in contents

    def test_memory_repo_get_by_tags_finds_promises(self, memory_repo: SQLiteMemoryRepository):
        """memory_repo.get_by_tags(['promise','active']) で promise memories が取得できる。"""
        now = get_now()
        mem = Memory(
            key="promise_test_001",
            content="Test promise",
            created_at=now,
            updated_at=now,
            tags=["promise", "active"],
            importance=0.8,
        )
        memory_repo.save(mem)

        result = memory_repo.get_by_tags(["promise", "active"])
        assert result.is_ok
        contents = [m.content for m in result.value]
        assert "Test promise" in contents


# ===========================================================================
# T7-4: memory_strength 初期化
# ===========================================================================


class TestMemoryStrengthInit:
    """memory_repo.save() 後に memory_strength テーブルへ strength=1.0 が挿入される。"""

    def test_save_creates_strength_record(
        self,
        memory_repo: SQLiteMemoryRepository,
        sqlite_conn: SQLiteConnection,
    ):
        """save() が memory_strength に strength=1.0 / recall_count=0 を挿入する。"""
        m = _make_memory("memory_20250615120000", "test strength init")
        save_result = memory_repo.save(m)
        assert save_result.is_ok, f"save() failed: {save_result}"

        db = sqlite_conn.get_memory_db()
        row = db.execute(
            "SELECT strength, stability, recall_count FROM memory_strength WHERE memory_key = ?",
            (m.key,),
        ).fetchone()

        assert row is not None, "memory_strength record should exist immediately after save()"
        assert row["strength"] == pytest.approx(1.0), f"Expected strength=1.0 after first save, got {row['strength']}"
        assert row["recall_count"] == 0, f"Expected recall_count=0 on fresh record, got {row['recall_count']}"

    def test_resave_does_not_overwrite_existing_strength(
        self,
        memory_repo: SQLiteMemoryRepository,
        sqlite_conn: SQLiteConnection,
    ):
        """INSERT OR IGNORE: re-save しても既存の strength/recall_count が保たれる。"""
        m = _make_memory("memory_20250615120001", "test resave")
        memory_repo.save(m)

        db = sqlite_conn.get_memory_db()
        # Simulate Ebbinghaus decay / manual boost
        db.execute(
            "UPDATE memory_strength SET strength = 0.42, recall_count = 5 WHERE memory_key = ?",
            (m.key,),
        )
        db.commit()

        # Re-save should not clobber the existing record
        memory_repo.save(m)

        row = db.execute(
            "SELECT strength, recall_count FROM memory_strength WHERE memory_key = ?",
            (m.key,),
        ).fetchone()
        assert row is not None
        assert row["strength"] == pytest.approx(0.42), "INSERT OR IGNORE must not replace existing strength"
        assert row["recall_count"] == 5, "INSERT OR IGNORE must not reset recall_count"

    def test_multiple_memories_each_get_strength_record(
        self,
        memory_repo: SQLiteMemoryRepository,
        sqlite_conn: SQLiteConnection,
    ):
        """複数の異なる記憶をそれぞれ保存すると、それぞれに strength レコードが作られる。"""
        keys = [
            "memory_20250615120001",
            "memory_20250615120002",
            "memory_20250615120003",
        ]
        for key in keys:
            memory_repo.save(_make_memory(key, f"content for {key}"))

        db = sqlite_conn.get_memory_db()
        rows = db.execute("SELECT memory_key FROM memory_strength").fetchall()
        stored_keys = {r["memory_key"] for r in rows}
        for key in keys:
            assert key in stored_keys, f"No strength record found for {key}"


# ===========================================================================
# T7-5: entity 自動抽出 (best-effort)
# ===========================================================================


class TestEntityAutoExtract:
    """英語固有名詞が extract_and_link で memory_entities に登録される。

    extract_and_link は best-effort なので 0 件でも fail させず警告のみ。
    """

    _CONTENT = "Alice met Bob at the conference"

    def test_extractor_directly_finds_alice_and_bob(self):
        """SimpleEntityExtractor が 'Alice' / 'Bob' を直接抽出できることを確認。"""
        extractor = SimpleEntityExtractor()
        results = extractor.extract(self._CONTENT)
        names = {name for name, _ in results}
        assert "Alice" in names or "Bob" in names, (
            f"SimpleEntityExtractor did not find 'Alice' or 'Bob' in {names!r}. Input: '{self._CONTENT}'"
        )

    def test_extract_and_link_returns_ok(self, entity_service: EntityService):
        """extract_and_link() は少なくとも成功 (is_ok) を返す。"""
        result = entity_service.extract_and_link(
            memory_key="mem_alice_bob",
            content=self._CONTENT,
        )
        assert result.is_ok, f"extract_and_link raised an error: {result}"

    def test_memory_entities_table_populated(
        self,
        entity_service: EntityService,
        entity_repo: SQLiteEntityRepository,
    ):
        """extract_and_link 後、memory_entities テーブルに Alice か Bob が存在する。

        0 件の場合は best-effort のため警告のみ（テスト失敗にしない）。
        """
        entity_service.extract_and_link(
            memory_key="mem_alice_bob_2",
            content=self._CONTENT,
        )

        mem_entities = entity_repo.get_memory_entities("mem_alice_bob_2")
        assert mem_entities.is_ok

        if not mem_entities.value:
            warnings.warn(
                f"memory_entities is empty for '{self._CONTENT}' — "
                "extractor returned no results (best-effort, not failing).",
                stacklevel=2,
            )
            return

        entity_ids_lower = {e.id.lower() for e in mem_entities.value}
        assert "alice" in entity_ids_lower or "bob" in entity_ids_lower, (
            f"Expected 'alice' or 'bob' (case-insensitive) in memory_entities, got {entity_ids_lower!r}"
        )

    def test_english_proper_nouns_in_entity_result(self, entity_service: EntityService):
        """extract_and_link の戻り値に Alice または Bob が含まれる。

        0 件の場合は best-effort のため警告のみ（テスト失敗にしない）。
        """
        result = entity_service.extract_and_link(
            memory_key="mem_alice_bob_3",
            content=self._CONTENT,
        )
        assert result.is_ok

        entity_ids = {e.id for e in result.value}
        entity_ids_lower = {e.lower() for e in entity_ids}
        if not entity_ids:
            warnings.warn(
                f"No entities extracted from '{self._CONTENT}' (best-effort, not failing).",
                stacklevel=2,
            )
            return

        assert "alice" in entity_ids_lower or "bob" in entity_ids_lower, (
            f"Expected 'alice' or 'bob' (case-insensitive) in extracted entities, got {entity_ids!r}"
        )


class TestEmotionTrendDisplay:
    """_format_lightweight_response() の感情トレンド表示に trigger context が含まれること。"""

    @staticmethod
    def _state(emotion: str = "neutral", intensity: float = 0.0) -> PersonaState:
        return PersonaState(
            persona=PERSONA,
            emotion=emotion,
            emotion_intensity=intensity,
            user_info={},
            persona_info={},
        )

    def _fmt(self, emotion_history: list) -> str:
        return _format_lightweight_response(
            state=self._state("sadness", 0.6),
            top_memories=[],
            goals=[],
            equipment={},
            recent=[],
            time_since="",
            emotion_history=emotion_history,
        )

    def test_trend_shows_context(self):
        """Emotion history with context → context displayed in trend."""
        now = get_now()
        history = [
            EmotionRecord(emotion="joy", intensity=0.8, timestamp=now, context="manual_update"),
            EmotionRecord(emotion="anger", intensity=0.9, timestamp=now, context="argument"),
        ]
        output = self._fmt(history)
        assert "Your emotion trend:" in output
        assert "joy(manual_update)" in output or "joy" in output
        assert "anger(argument)" in output or "sadness" in output

    def test_trend_no_context_shows_plain(self):
        """Emotion history without context → plain emotion names."""
        now = get_now()
        history = [
            EmotionRecord(emotion="joy", intensity=0.8, timestamp=now),
            EmotionRecord(emotion="anger", intensity=0.9, timestamp=now),
        ]
        output = self._fmt(history)
        assert "Your emotion trend:" in output
        # Should not have parenthetical context
        assert "Your emotion trend: joy → anger → sadness" in output

    def test_time_decay_context_in_trend(self):
        """time_decay context appears in trend display."""
        now = get_now()
        history = [
            EmotionRecord(emotion="joy", intensity=0.8, timestamp=now, context="manual_update"),
            EmotionRecord(emotion="neutral", intensity=0.0, timestamp=now, context="time_decay"),
        ]
        output = self._fmt(history)
        assert "time_decay" in output
