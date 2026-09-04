"""Unit tests for JSONLImporter."""

from __future__ import annotations

import json

import pytest

from nous.migration.importers.jsonl_importer import JSONLImporter


@pytest.fixture
def importer():
    return JSONLImporter()


class TestJSONLImporter:
    def test_import_valid_memories(self, tmp_path, sqlite_conn, importer):
        """Import a valid JSONL file with memory records."""
        records = [
            {"type": "memory", "key": "mem_001", "content": "Hello world", "importance": 0.7},
            {"type": "memory", "key": "mem_002", "content": "Goodbye world"},
        ]
        file_path = tmp_path / "import.jsonl"
        file_path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

        result = importer.import_file(str(file_path), sqlite_conn, "test")
        assert result.is_ok
        counts = result.value
        assert counts["memory"] == 2

    def test_import_invalid_json_lines_skipped(self, tmp_path, sqlite_conn, importer):
        """Lines with invalid JSON should be skipped gracefully."""
        lines = [
            json.dumps({"type": "memory", "key": "mem_001", "content": "valid"}),
            "this is not valid json {{{",
            json.dumps({"type": "memory", "key": "mem_002", "content": "also valid"}),
        ]
        file_path = tmp_path / "import.jsonl"
        file_path.write_text("\n".join(lines), encoding="utf-8")

        result = importer.import_file(str(file_path), sqlite_conn, "test")
        assert result.is_ok
        assert result.value["memory"] == 2

    def test_import_empty_lines_skipped(self, tmp_path, sqlite_conn, importer):
        """Empty lines should be skipped."""
        lines = [
            json.dumps({"type": "memory", "key": "mem_001", "content": "valid"}),
            "",
            "   ",
            json.dumps({"type": "memory", "key": "mem_002", "content": "also valid"}),
        ]
        file_path = tmp_path / "import.jsonl"
        file_path.write_text("\n".join(lines), encoding="utf-8")

        result = importer.import_file(str(file_path), sqlite_conn, "test")
        assert result.is_ok
        assert result.value["memory"] == 2

    def test_import_missing_type_defaults_to_memory(self, tmp_path, sqlite_conn, importer):
        """Records without a type field default to memory."""
        data = {"content": "no type field", "key": "mem_notype"}
        file_path = tmp_path / "import.jsonl"
        file_path.write_text(json.dumps(data), encoding="utf-8")

        result = importer.import_file(str(file_path), sqlite_conn, "test")
        assert result.is_ok
        assert result.value["memory"] == 1

    def test_import_state_records(self, tmp_path, sqlite_conn, importer):
        """State records should be imported to context_state table."""
        data = {"type": "state", "key": "emotion", "value": "joy", "persona": "test"}
        file_path = tmp_path / "import.jsonl"
        file_path.write_text(json.dumps(data), encoding="utf-8")

        result = importer.import_file(str(file_path), sqlite_conn, "test")
        assert result.is_ok
        assert result.value["state"] == 1

    def test_import_item_records(self, tmp_path, sqlite_conn, importer):
        """Item records should be imported to items table."""
        data = {"type": "item", "name": "sword", "category": "weapon"}
        file_path = tmp_path / "import.jsonl"
        file_path.write_text(json.dumps(data), encoding="utf-8")

        result = importer.import_file(str(file_path), sqlite_conn, "test")
        assert result.is_ok
        assert result.value["item"] == 1

    def test_import_emotion_records(self, tmp_path, sqlite_conn, importer):
        """Emotion records should be imported to emotion_history table."""
        data = {"type": "emotion", "emotion_type": "joy", "intensity": 0.8}
        file_path = tmp_path / "import.jsonl"
        file_path.write_text(json.dumps(data), encoding="utf-8")

        result = importer.import_file(str(file_path), sqlite_conn, "test")
        assert result.is_ok
        assert result.value["emotion"] == 1

    def test_import_block_records(self, tmp_path, sqlite_conn, importer):
        """Block records should be imported to memory_blocks table."""
        data = {"type": "block", "block_name": "system_prompt", "content": "You are helpful."}
        file_path = tmp_path / "import.jsonl"
        file_path.write_text(json.dumps(data), encoding="utf-8")

        result = importer.import_file(str(file_path), sqlite_conn, "test")
        assert result.is_ok
        assert result.value["block"] == 1

    def test_import_nonexistent_file_returns_failure(self, tmp_path, sqlite_conn, importer):
        """Non-existent file should return Failure."""
        result = importer.import_file(str(tmp_path / "nonexistent.jsonl"), sqlite_conn, "test")
        assert not result.is_ok

    def test_import_memory_with_all_optional_fields(self, tmp_path, sqlite_conn, importer):
        """Import a memory with all optional fields populated."""
        data = {
            "type": "memory",
            "key": "mem_full",
            "content": "Full memory",
            "importance": 0.9,
            "emotion": "joy",
            "emotion_intensity": 0.8,
            "tags": '["tag1", "tag2"]',
            "physical_state": "relaxed",
            "mental_state": "focused",
            "environment": "home",
            "relationship_status": "partner",
            "action_tag": "reading",
            "privacy_level": "private",
            "source_context": "manual_entry",
            "access_count": 5,
        }
        file_path = tmp_path / "import.jsonl"
        file_path.write_text(json.dumps(data), encoding="utf-8")

        result = importer.import_file(str(file_path), sqlite_conn, "test")
        assert result.is_ok
        assert result.value["memory"] == 1

    def test_import_mixed_types(self, tmp_path, sqlite_conn, importer):
        """Import file with multiple record types returns correct counts."""
        records = [
            {"type": "memory", "key": "mem_001", "content": "Test memory"},
            {"type": "state", "key": "emotion", "value": "happy"},
            {"type": "item", "name": "book"},
            {"type": "emotion", "emotion_type": "curiosity"},
            {"type": "block", "block_name": "notes", "content": "some notes"},
        ]
        file_path = tmp_path / "import.jsonl"
        file_path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

        result = importer.import_file(str(file_path), sqlite_conn, "test")
        assert result.is_ok
        counts = result.value
        assert counts["memory"] == 1
        assert counts["state"] == 1
        assert counts["item"] == 1
        assert counts["emotion"] == 1
        assert counts["block"] == 1

    def test_import_unknown_type_ignored(self, tmp_path, sqlite_conn, importer):
        """Records with an unknown type are ignored (not counted in any bucket)."""
        records = [
            {"type": "unknown_type", "data": "whatever"},
            {"type": "memory", "key": "mem_001", "content": "valid"},
        ]
        file_path = tmp_path / "import.jsonl"
        file_path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

        result = importer.import_file(str(file_path), sqlite_conn, "test")
        assert result.is_ok
        counts = result.value
        assert counts["memory"] == 1
        # unknown type doesn't increment any counter
        assert sum(counts.values()) == 1
