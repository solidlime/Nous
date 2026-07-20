from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from nous.domain.skill import Skill, SkillRepository, _parse_skill_md


def _make_db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute("""
        CREATE TABLE skills (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT UNIQUE NOT NULL,
            description   TEXT DEFAULT '',
            content       TEXT NOT NULL DEFAULT '',
            license       TEXT,
            compatibility TEXT,
            metadata      TEXT,
            created_at    TEXT,
            updated_at    TEXT
        )
    """)
    db.commit()
    db.row_factory = sqlite3.Row
    return db


class TestSkillRepository:
    def test_list_empty(self):
        db = _make_db()
        repo = SkillRepository(db)
        assert repo.list_all() == []

    def test_save_and_get(self):
        db = _make_db()
        repo = SkillRepository(db)
        skill = Skill(name="coder", description="コードを書く", content="You are a coder.")
        saved = repo.save(skill)
        assert saved.id is not None
        assert saved.name == "coder"
        loaded = repo.get("coder")
        assert loaded is not None
        assert loaded.name == "coder"
        assert loaded.description == "コードを書く"
        assert loaded.content == "You are a coder."

    def test_get_nonexistent(self):
        db = _make_db()
        repo = SkillRepository(db)
        assert repo.get("nonexistent") is None

    def test_list_all(self):
        db = _make_db()
        repo = SkillRepository(db)
        repo.save(Skill(name="skill_b", content="b"))
        repo.save(Skill(name="skill_a", content="a"))
        skills = repo.list_all()
        assert len(skills) == 2
        # sorted by name
        assert skills[0].name == "skill_a"
        assert skills[1].name == "skill_b"

    def test_save_update(self):
        db = _make_db()
        repo = SkillRepository(db)
        saved = repo.save(Skill(name="x", content="old"))
        updated = repo.save(Skill(id=saved.id, name="x", content="new", created_at=saved.created_at))
        assert updated.content == "new"
        loaded = repo.get("x")
        assert loaded is not None
        assert loaded.content == "new"

    def test_upsert_creates_new(self):
        db = _make_db()
        repo = SkillRepository(db)
        saved = repo.upsert(Skill(name="newskill", content="hello"))
        assert saved.id is not None
        assert repo.get("newskill") is not None

    def test_upsert_updates_existing(self):
        db = _make_db()
        repo = SkillRepository(db)
        repo.save(Skill(name="existing", content="old"))
        repo.upsert(Skill(name="existing", content="updated"))
        loaded = repo.get("existing")
        assert loaded is not None
        assert loaded.content == "updated"

    def test_delete(self):
        db = _make_db()
        repo = SkillRepository(db)
        repo.save(Skill(name="todelete", content="bye"))
        repo.delete("todelete")
        assert repo.get("todelete") is None

    def test_delete_nonexistent_no_error(self):
        db = _make_db()
        repo = SkillRepository(db)
        repo.delete("doesnotexist")  # should not raise

    # ── Extended fields tests ──

    def test_save_with_extended_fields(self):
        db = _make_db()
        repo = SkillRepository(db)
        meta = {"key1": "val1", "key2": "val2"}
        skill = Skill(
            name="extended",
            description="test",
            content="body",
            license="MIT",
            compatibility="memory-mcp >= 2.0.0",
            metadata=meta,
        )
        saved = repo.save(skill)
        assert saved.license == "MIT"
        assert saved.compatibility == "memory-mcp >= 2.0.0"
        assert saved.metadata == meta

        loaded = repo.get("extended")
        assert loaded is not None
        assert loaded.license == "MIT"
        assert loaded.compatibility == "memory-mcp >= 2.0.0"
        assert loaded.metadata == meta

    def test_list_all_with_extended_fields(self):
        db = _make_db()
        repo = SkillRepository(db)
        repo.save(
            Skill(
                name="skill1",
                content="c1",
                license="MIT",
                compatibility="v1",
                metadata={"env": "prod"},
            )
        )
        repo.save(
            Skill(
                name="skill2",
                content="c2",
                license="Apache-2.0",
                compatibility="v2",
                metadata={"env": "staging"},
            )
        )
        skills = repo.list_all()
        assert len(skills) == 2
        s1 = skills[0]
        assert s1.name == "skill1"
        assert s1.license == "MIT"
        assert s1.compatibility == "v1"
        assert s1.metadata == {"env": "prod"}
        s2 = skills[1]
        assert s2.name == "skill2"
        assert s2.license == "Apache-2.0"
        assert s2.compatibility == "v2"
        assert s2.metadata == {"env": "staging"}

    def test_upsert_preserves_extended_fields(self):
        db = _make_db()
        repo = SkillRepository(db)
        repo.upsert(
            Skill(
                name="test",
                content="original",
                license="MIT",
                compatibility="v1",
                metadata={"k": "v"},
            )
        )
        repo.upsert(Skill(name="test", content="updated"))
        loaded = repo.get("test")
        assert loaded is not None
        assert loaded.content == "updated"
        # upsert overwrites all fields
        assert loaded.license is None
        assert loaded.compatibility is None
        assert loaded.metadata is None


class TestParseSkillMd:
    def test_basic_frontmatter(self):
        raw = "---\nname: hello\ndescription: A test\n---\nBody text"
        result = _parse_skill_md("dir", raw)
        assert result["name"] == "hello"
        assert result["description"] == "A test"
        assert result["content"] == "Body text"

    def test_no_frontmatter(self):
        raw = "Just content here"
        result = _parse_skill_md("mydir", raw)
        assert result["name"] == "mydir"
        assert result["description"] == ""
        assert result["content"] == "Just content here"

    def test_partial_frontmatter(self):
        raw = "---\ndescription: only desc\n---\nBody"
        result = _parse_skill_md("mydir", raw)
        # name falls back to dir_name when not in frontmatter
        assert result["name"] == "mydir"
        assert result["description"] == "only desc"
        assert result["content"] == "Body"

    def test_parse_extended_frontmatter(self):
        raw = """---
name: my-skill
description: A test skill
license: MIT
compatibility: memory-mcp >= 2.0.0
metadata: {"author": "helta", "version": "1"}
---
Body content
"""
        result = _parse_skill_md("dir", raw)
        assert result["name"] == "my-skill"
        assert result["description"] == "A test skill"
        assert result["license"] == "MIT"
        assert result["compatibility"] == "memory-mcp >= 2.0.0"
        assert result["metadata"] == {"author": "helta", "version": "1"}
        assert result["content"] == "Body content"

    def test_parse_metadata_invalid_json(self):
        raw = "---\nname: test\nmetadata: {invalid\n---\nBody"
        result = _parse_skill_md("dir", raw)
        # invalid JSON metadata is ignored, stays None
        assert result["metadata"] is None

    def test_name_validation_valid(self):
        raw = "---\nname: valid-name-123\n---\nBody"
        result = _parse_skill_md("dir", raw)
        assert result["name"] == "valid-name-123"

    def test_name_validation_invalid_chars(self):
        raw = "---\nname: Invalid_Name!\n---\nBody"
        result = _parse_skill_md("dir", raw)
        # invalid name falls back to dir_name
        assert result["name"] == "dir"

    def test_name_validation_leading_hyphen(self):
        raw = "---\nname: -bad-name\n---\nBody"
        result = _parse_skill_md("dir", raw)
        assert result["name"] == "dir"

    def test_name_validation_too_long(self):
        raw = "---\nname: " + "a" * 65 + "\n---\nBody"
        result = _parse_skill_md("dir", raw)
        assert result["name"] == "dir"

    def test_name_validation_empty(self):
        raw = "---\nname: \n---\nBody"
        result = _parse_skill_md("dir", raw)
        assert result["name"] == "dir"

    def test_skill_repository_metadata_roundtrip(self):
        """Verify metadata survives JSON serialize/deserialize through the DB."""
        db = _make_db()
        repo = SkillRepository(db)
        meta = {"key1": "val1", "author": "helta"}
        skill = Skill(
            name="roundtrip",
            description="test",
            content="body",
            license="MIT",
            compatibility=">=1.0",
            metadata=meta,
        )
        repo.save(skill)
        loaded = repo.get("roundtrip")
        assert loaded is not None
        assert loaded.metadata == meta

    def test_skill_repository_none_metadata(self):
        """Verify None metadata is stored as NULL and loaded as None."""
        db = _make_db()
        repo = SkillRepository(db)
        skill = Skill(name="nometa", description="test", content="body")
        repo.save(skill)
        loaded = repo.get("nometa")
        assert loaded is not None
        assert loaded.metadata is None
        assert loaded.license is None
        assert loaded.compatibility is None

    def test_load_from_dir_with_extended(self, tmp_path):
        db = _make_db()
        repo = SkillRepository(db)
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()
        skill_sub = skill_dir / "my-tool"
        skill_sub.mkdir()
        md = skill_sub / "SKILL.md"
        md.write_text(
            "---\n"
            "name: my-tool\n"
            "description: My tool\n"
            "license: MIT\n"
            "compatibility: >=1.0\n"
            'metadata: {"key": "val"}\n'
            "---\n"
            "Tool body here\n",
            encoding="utf-8",
        )
        result = repo.load_from_dir(str(skill_dir))
        assert len(result) == 1
        s = result[0]
        assert s.name == "my-tool"
        assert s.license == "MIT"
        assert s.compatibility == ">=1.0"
        assert s.metadata == {"key": "val"}
        assert s.content == "Tool body here"


def test_skills_pre_installed():
    """Verify the pre-installed skills exist and can be loaded from /opt/nous/skills."""
    from nous.config.settings import get_settings

    skills_dir = Path(get_settings().skills_dir)
    if not skills_dir.is_dir():
        pytest.skip(f"Global skills dir not available: {skills_dir}")

    db = _make_db()
    repo = SkillRepository(db)
    skills = repo.load_from_dir(str(skills_dir))

    names = {s.name for s in skills}

    assert len(skills) >= 5, f"Expected at least 5 skills, got {len(skills)}"
    assert "auto-memory" in names, "Missing: auto-memory"
    assert "auto-self-portrait" in names, "Missing: auto-self-portrait"
    assert "goal-coach" in names, "Missing: goal-coach"
    assert "mood-sync" in names, "Missing: mood-sync"
    assert "recall-weaver" in names, "Missing: recall-weaver"

    # Each skill must have a non-empty description and content
    for s in skills:
        assert s.description, f"Skill '{s.name}' has empty description"
        assert s.content, f"Skill '{s.name}' has empty content"
