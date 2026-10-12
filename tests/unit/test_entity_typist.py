"""Tests for the entity typist: LLM typing, trust-gated UPDATE, and backfill runner (#011)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.domain.memory.graph import Entity
from nous.infrastructure.sqlite.entity_repo import SQLiteEntityRepository

# ===========================================================================
# LLMEntityTypist — prompt, parse, fail-open, batching
# ===========================================================================


def _typist():
    from nous.infrastructure.llm.entity_typist import LLMEntityTypist

    return LLMEntityTypist(provider_name="openai", api_key="k", model="m")


class TestEntityTypistPrompt:
    def test_prompt_includes_snippets_and_name(self):
        from nous.infrastructure.llm.entity_typist import LLMEntityTypist

        msg = LLMEntityTypist._build_user_message(
            [{"id": "プリン", "current_type": "entity", "snippets": ["プリンとクッキーを買った"]}]
        )
        assert "プリン" in msg
        assert "プリンとクッキーを買った" in msg

    def test_prompt_requests_all_entities_by_index(self):
        from nous.infrastructure.llm.entity_typist import LLMEntityTypist

        msg = LLMEntityTypist._build_user_message(
            [
                {"id": "a", "current_type": "unknown", "snippets": []},
                {"id": "b", "current_type": "unknown", "snippets": []},
            ]
        )
        assert "[0]" in msg
        assert "[1]" in msg


class TestEntityTypistParse:
    def test_parse_maps_valid_types(self):
        from nous.infrastructure.llm.entity_typist import LLMEntityTypist

        items = [{"id": "ヘルタ"}, {"id": "プリン"}, {"id": "東京"}]
        text = json.dumps(
            {"types": [{"index": 0, "type": "person"}, {"index": 1, "type": "thing"}, {"index": 2, "type": "place"}]}
        )
        assert LLMEntityTypist._parse(text, items) == {"ヘルタ": "person", "プリン": "thing", "東京": "place"}

    def test_parse_accepts_agent(self):
        from nous.infrastructure.llm.entity_typist import LLMEntityTypist

        items = [{"id": "ロボ"}]
        assert LLMEntityTypist._parse(json.dumps({"types": [{"index": 0, "type": "agent"}]}), items) == {
            "ロボ": "agent"
        }

    def test_parse_drops_unknown_vocab_and_bad_index(self):
        from nous.infrastructure.llm.entity_typist import LLMEntityTypist

        items = [{"id": "a"}, {"id": "b"}]
        text = json.dumps(
            {
                "types": [
                    {"index": 0, "type": "character"},
                    {"index": 5, "type": "person"},
                    {"index": 1, "type": "thing"},
                ]
            }
        )
        assert LLMEntityTypist._parse(text, items) == {"b": "thing"}

    def test_parse_normalises_location_alias(self):
        from nous.infrastructure.llm.entity_typist import LLMEntityTypist

        items = [{"id": "東京"}]
        assert LLMEntityTypist._parse(json.dumps({"types": [{"index": 0, "type": "location"}]}), items) == {
            "東京": "place"
        }

    def test_parse_bad_json_returns_none(self):
        from nous.infrastructure.llm.entity_typist import LLMEntityTypist

        assert LLMEntityTypist._parse("not json", [{"id": "a"}]) is None

    def test_parse_no_valid_entries_returns_none(self):
        from nous.infrastructure.llm.entity_typist import LLMEntityTypist

        assert LLMEntityTypist._parse(json.dumps({"types": []}), [{"id": "a"}]) is None


class TestEntityTypistFailOpen:
    async def test_llm_exception_returns_none(self):
        typist = _typist()
        with (
            patch("nous.infrastructure.llm.entity_typist.get_provider", return_value=MagicMock()),
            patch.object(typist, "_call_llm", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            assert await typist._type_batch([{"id": "a", "current_type": "unknown", "snippets": []}]) is None

    async def test_empty_text_returns_none(self):
        typist = _typist()
        with (
            patch("nous.infrastructure.llm.entity_typist.get_provider", return_value=MagicMock()),
            patch.object(typist, "_call_llm", new=AsyncMock(return_value=(None, None))),
        ):
            assert await typist._type_batch([{"id": "a", "current_type": "unknown", "snippets": []}]) is None


class TestEntityTypistBatching:
    async def test_type_many_batches_calls(self):
        typist = _typist()
        captured: list[list] = []

        async def _call(provider, user_message, n_items):
            captured.append([user_message])
            # echo back the first index as thing so each batch yields one mapping
            return json.dumps({"types": [{"index": 0, "type": "thing"}]}), None

        items = [{"id": f"e{i}", "current_type": "unknown", "snippets": []} for i in range(5)]
        with (
            patch("nous.infrastructure.llm.entity_typist.get_provider", return_value=MagicMock()),
            patch.object(typist, "_call_llm", side_effect=_call),
        ):
            typed = await typist.type_many(items, batch_size=2)

        assert len(captured) == 3  # 2 + 2 + 1
        assert len(typed) == 3


# ===========================================================================
# SQLiteEntityRepository — trust-gated UPDATE + worklist reads
# ===========================================================================


@pytest.fixture
def entity_repo(sqlite_conn):
    return SQLiteEntityRepository(sqlite_conn)


def _save(repo, eid, etype="unknown", metadata=None):
    repo.save_entity(Entity(id=eid, entity_type=etype, metadata=metadata or {}))


class TestUpdateEntityTypeTrust:
    def test_regex_typed_when_absent(self, entity_repo):
        _save(entity_repo, "p1")
        result = entity_repo.update_entity_type("p1", "person", "regex")
        assert result.is_ok and result.value is True
        ent = entity_repo.get_entity("p1").value
        assert ent.entity_type == "person"
        assert ent.metadata == {"typed_by": "regex"}

    def test_preserves_existing_metadata_keys(self, entity_repo):
        _save(entity_repo, "p1", metadata={"note": "keep"})
        entity_repo.update_entity_type("p1", "person", "llm")
        ent = entity_repo.get_entity("p1").value
        assert ent.metadata == {"note": "keep", "typed_by": "llm"}

    def test_sudachi_overwrites_regex(self, entity_repo):
        _save(entity_repo, "p1")
        entity_repo.update_entity_type("p1", "person", "regex")
        result = entity_repo.update_entity_type("p1", "place", "sudachi")
        assert result.value is True
        assert entity_repo.get_entity("p1").value.entity_type == "place"
        assert entity_repo.get_entity("p1").value.metadata["typed_by"] == "sudachi"

    def test_llm_overwrites_sudachi(self, entity_repo):
        _save(entity_repo, "p1")
        entity_repo.update_entity_type("p1", "place", "sudachi")
        assert entity_repo.update_entity_type("p1", "person", "llm").value is True

    def test_regex_cannot_overwrite_sudachi(self, entity_repo):
        _save(entity_repo, "p1")
        entity_repo.update_entity_type("p1", "place", "sudachi")
        result = entity_repo.update_entity_type("p1", "person", "regex")
        assert result.is_ok and result.value is False
        ent = entity_repo.get_entity("p1").value
        assert ent.entity_type == "place"
        assert ent.metadata["typed_by"] == "sudachi"

    def test_sudachi_cannot_overwrite_llm(self, entity_repo):
        _save(entity_repo, "p1")
        entity_repo.update_entity_type("p1", "person", "llm")
        assert entity_repo.update_entity_type("p1", "thing", "sudachi").value is False
        assert entity_repo.get_entity("p1").value.entity_type == "person"

    def test_same_trust_rejected(self, entity_repo):
        _save(entity_repo, "p1")
        entity_repo.update_entity_type("p1", "person", "llm")
        assert entity_repo.update_entity_type("p1", "thing", "llm").value is False

    def test_unknown_typed_by_rejected(self, entity_repo):
        _save(entity_repo, "p1")
        assert entity_repo.update_entity_type("p1", "person", "guessed").is_ok is False

    def test_missing_entity_returns_false(self, entity_repo):
        result = entity_repo.update_entity_type("nope", "person", "llm")
        assert result.is_ok and result.value is False


class TestTypistWorklist:
    def test_lists_entities_without_typed_by(self, entity_repo):
        _save(entity_repo, "a", etype="person")  # regex-typed, no typed_by
        _save(entity_repo, "b", etype="unknown")
        entity_repo.update_entity_type("b", "thing", "llm")  # now has typed_by
        ids = {r["id"] for r in entity_repo.list_entities_without_typed_by()}
        assert ids == {"a"}

    def test_typed_entities_excluded(self, entity_repo):
        _save(entity_repo, "a")
        entity_repo.update_entity_type("a", "person", "llm")
        assert entity_repo.list_entities_without_typed_by() == []

    def test_representative_snippets(self, sqlite_conn, entity_repo):
        db = sqlite_conn.get_memory_db()
        for key, content, imp in (
            ("m1", "プリンを買った", 0.9),
            ("m2", "プリンは甘い", 0.5),
            ("m3", "デザートの話", 0.7),
        ):
            db.execute(
                "INSERT INTO memories (key, content, created_at, updated_at, importance) VALUES (?, ?, ?, ?, ?)",
                (key, content, "2024-01-01", "2024-01-01", imp),
            )
        _save(entity_repo, "プリン")
        for key in ("m1", "m2", "m3"):
            entity_repo.link_memory_entity(key, "プリン")
        snippets = entity_repo.get_representative_snippets(["プリン"], per_entity=2)
        assert snippets["プリン"] == ["プリンを買った", "デザートの話"]


# ===========================================================================
# Backfill runner
# ===========================================================================


class _FakeTypist:
    def __init__(self, mapping):
        self._mapping = mapping
        self.calls: list[list] = []

    async def type_many(self, items, batch_size=20):
        self.calls.append(items)
        return {k: v for k, v in self._mapping.items()}


class TestRunEntityTypist:
    async def test_applies_llm_types(self, sqlite_conn, entity_repo):
        from nous.application.entity_typist import run_entity_typist

        _save(entity_repo, "ヘルタ", etype="person")
        _save(entity_repo, "プリン", etype="entity")
        typist = _FakeTypist({"ヘルタ": "person", "プリン": "thing"})
        report = await run_entity_typist(entity_repo, typist)

        assert report.examined == 2
        assert report.typed == 2
        assert entity_repo.get_entity("プリン").value.entity_type == "thing"
        assert entity_repo.get_entity("プリン").value.metadata["typed_by"] == "llm"

    async def test_passes_snippets_to_typist(self, sqlite_conn, entity_repo):
        from nous.application.entity_typist import run_entity_typist

        db = sqlite_conn.get_memory_db()
        db.execute(
            "INSERT INTO memories (key, content, created_at, updated_at) VALUES ('m1', 'プリンとクッキー', '2024-01-01', '2024-01-01')"
        )
        _save(entity_repo, "プリン")
        entity_repo.link_memory_entity("m1", "プリン")
        typist = _FakeTypist({})
        await run_entity_typist(entity_repo, typist)
        item = typist.calls[0][0]
        assert item["id"] == "プリン"
        assert "プリンとクッキー" in item["snippets"][0]

    async def test_fail_open_when_typist_returns_empty(self, sqlite_conn, entity_repo):
        from nous.application.entity_typist import run_entity_typist

        _save(entity_repo, "プリン", etype="entity")
        report = await run_entity_typist(entity_repo, _FakeTypist({}))
        assert report.typed == 0
        assert entity_repo.get_entity("プリン").value.entity_type == "entity"
        assert "typed_by" not in entity_repo.get_entity("プリン").value.metadata

    async def test_fail_open_when_typist_raises(self, sqlite_conn, entity_repo):
        from nous.application.entity_typist import run_entity_typist

        class _Boom:
            async def type_many(self, items, batch_size=20):
                raise RuntimeError("boom")

        _save(entity_repo, "プリン", etype="entity")
        report = await run_entity_typist(entity_repo, _Boom())
        assert report.typed == 0

    async def test_lower_trust_not_clobbered(self, sqlite_conn, entity_repo):
        from nous.application.entity_typist import run_entity_typist

        _save(entity_repo, "p1")
        entity_repo.update_entity_type("p1", "place", "sudachi")
        # runner only sees entities without typed_by, so p1 is skipped entirely
        typist = _FakeTypist({"p1": "person"})
        report = await run_entity_typist(entity_repo, typist)
        assert report.examined == 0
        assert entity_repo.get_entity("p1").value.entity_type == "place"


# ===========================================================================
# Sudachi vocabulary — location → place (canonical)
# ===========================================================================


class TestSudachiVocabulary:
    def test_place_name_classified_as_place(self):
        from nous.domain.memory.sudachi_extractor import SudachiExtractor

        assert SudachiExtractor._classify(["名詞", "固有名詞", "地名"]) == "place"
