"""Unit tests for JSONLExporter."""

from __future__ import annotations

import json

import pytest

from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.migration.exporters.jsonl_exporter import JSONLExporter
from nous.migration.importers.jsonl_importer import JSONLImporter


@pytest.fixture
def exporter():
    return JSONLExporter()


def _insert_memory(db, key, content, now="2025-01-01T00:00:00+09:00", importance=0.5):
    db.execute(
        "INSERT INTO memories (key, content, created_at, updated_at, importance) VALUES (?,?,?,?,?)",
        (key, content, now, now, importance),
    )
    db.commit()


class TestJSONLExporter:
    def test_export_empty_db(self, tmp_path, sqlite_conn, exporter):
        """Export an empty database should succeed with zero records."""
        output_path = tmp_path / "export.jsonl"
        result = exporter.export_persona(sqlite_conn, "test", str(output_path))
        assert result.is_ok
        assert result.value == 0
        assert output_path.exists()

    def test_export_with_memories(self, tmp_path, sqlite_conn, exporter):
        """Export a database with memories produces correct JSONL."""
        db = sqlite_conn.get_memory_db()
        _insert_memory(db, "mem_001", "Test content")

        output_path = tmp_path / "export.jsonl"
        result = exporter.export_persona(sqlite_conn, "test", str(output_path))
        assert result.is_ok
        assert result.value >= 1

        lines = [ln for ln in output_path.read_text(encoding="utf-8").split("\n") if ln.strip()]
        records = [json.loads(ln) for ln in lines]
        memory_records = [r for r in records if r["type"] == "memory"]
        assert len(memory_records) == 1
        assert memory_records[0]["content"] == "Test content"

    def test_every_exported_record_has_type_field(self, tmp_path, sqlite_conn, exporter):
        """Each exported line must have a 'type' field."""
        db = sqlite_conn.get_memory_db()
        _insert_memory(db, "mem_001", "content")

        output_path = tmp_path / "out.jsonl"
        exporter.export_persona(sqlite_conn, "test", str(output_path))

        for line in output_path.read_text(encoding="utf-8").split("\n"):
            if line.strip():
                record = json.loads(line)
                assert "type" in record

    def test_export_multiple_memories(self, tmp_path, sqlite_conn, exporter):
        """Multiple memories are all exported."""
        db = sqlite_conn.get_memory_db()
        for i in range(3):
            _insert_memory(db, f"mem_{i:03d}", f"Memory {i}")

        output_path = tmp_path / "export.jsonl"
        exporter.export_persona(sqlite_conn, "test", str(output_path))

        lines = [ln for ln in output_path.read_text(encoding="utf-8").split("\n") if ln.strip()]
        records = [json.loads(ln) for ln in lines]
        memory_records = [r for r in records if r["type"] == "memory"]
        assert len(memory_records) == 3

    def test_round_trip_export_then_import(self, tmp_path, sqlite_conn, exporter):
        """Export then re-import should preserve memory key and content."""
        db = sqlite_conn.get_memory_db()
        _insert_memory(db, "mem_original", "Round trip content", importance=0.8)

        export_path = tmp_path / "export.jsonl"
        export_result = exporter.export_persona(sqlite_conn, "test", str(export_path))
        assert export_result.is_ok

        # Import into a fresh connection
        conn2 = SQLiteConnection(data_dir=str(tmp_path / "fresh"), persona="test2")
        conn2.initialize_schema()
        try:
            importer = JSONLImporter()
            import_result = importer.import_file(str(export_path), conn2, "test2")
            assert import_result.is_ok

            row = conn2.get_memory_db().execute("SELECT * FROM memories WHERE key = ?", ("mem_original",)).fetchone()
            assert row is not None
            assert row["content"] == "Round trip content"
        finally:
            conn2.close()

    def test_export_failure_on_bad_path(self, tmp_path, sqlite_conn, exporter):
        """Export to a path in a non-existent directory returns Failure."""
        bad_path = str(tmp_path / "no_such_dir" / "subdir" / "out.jsonl")
        result = exporter.export_persona(sqlite_conn, "test", bad_path)
        assert not result.is_ok

    def test_export_includes_context_state_for_persona(self, tmp_path, sqlite_conn, exporter):
        """context_state rows for the persona are exported as 'state' type."""
        db = sqlite_conn.get_memory_db()
        now = "2025-01-01T00:00:00+09:00"
        db.execute(
            "INSERT INTO context_state (persona, key, value, valid_from) VALUES (?,?,?,?)",
            ("test", "emotion", "joy", now),
        )
        db.commit()

        output_path = tmp_path / "export.jsonl"
        result = exporter.export_persona(sqlite_conn, "test", str(output_path))
        assert result.is_ok

        lines = [ln for ln in output_path.read_text(encoding="utf-8").split("\n") if ln.strip()]
        records = [json.loads(ln) for ln in lines]
        state_records = [r for r in records if r["type"] == "state"]
        assert len(state_records) == 1
        assert state_records[0]["value"] == "joy"
