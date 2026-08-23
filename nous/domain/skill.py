from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from nous.domain.shared.time_utils import format_iso, get_now

if TYPE_CHECKING:
    import sqlite3

_logger: Any = None  # lazy import


def _get_logger():
    global _logger
    if _logger is None:
        from nous.infrastructure.logging.structured import get_logger

        _logger = get_logger(__name__)
    return _logger


# a-z, 0-9, - only, 1-64 chars, no leading/trailing hyphen
_VALID_SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")


class Skill(BaseModel):
    id: int | None = None
    name: str
    description: str = ""
    content: str = ""
    license: str | None = None
    compatibility: str | None = None
    metadata: dict[str, str] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class SkillRepository:
    def __init__(self, db: sqlite3.Connection | None = None) -> None:
        self._db = db

    def _require_db(self) -> sqlite3.Connection:
        if self._db is None:
            msg = "SkillRepository has no database connection (DB mode deprecated)"
            raise RuntimeError(msg)
        return self._db

    @staticmethod
    def _parse_metadata(raw: str | None) -> dict[str, str] | None:
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _dump_metadata(meta: dict[str, str] | None) -> str | None:
        if meta is None:
            return None
        return json.dumps(meta, ensure_ascii=False)

    @staticmethod
    def _row_to_skill(r: sqlite3.Row) -> Skill:
        return Skill(
            id=r[0],
            name=r[1],
            description=r[2] or "",
            content=r[3] or "",
            license=r[4] if r[4] else None,
            compatibility=r[5] if r[5] else None,
            metadata=SkillRepository._parse_metadata(r[6]),
            created_at=r[7],
            updated_at=r[8],
        )

    _SELECT_COLS = "id, name, description, content, license, compatibility, metadata, created_at, updated_at"

    def list_all(self) -> list[Skill]:
        if self._db is None:
            return []
        rows = self._db.execute(
            f"SELECT {self._SELECT_COLS} FROM skills ORDER BY name"  # _SELECT_COLS is a class constant  # nosec B608
        ).fetchall()
        return [self._row_to_skill(r) for r in rows]

    def get(self, name: str) -> Skill | None:
        if self._db is None:
            return None
        row = self._db.execute(
            f"SELECT {self._SELECT_COLS} FROM skills WHERE name = ?",  # _SELECT_COLS class constant; name bound via param  # nosec B608
            (name,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_skill(row)

    def save(self, skill: Skill) -> Skill:
        db = self._require_db()
        now = format_iso(get_now())
        if skill.id is None:
            cursor = db.execute(
                "INSERT INTO skills (name, description, content, license, compatibility, metadata, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    skill.name,
                    skill.description,
                    skill.content,
                    skill.license,
                    skill.compatibility,
                    self._dump_metadata(skill.metadata),
                    now,
                    now,
                ),
            )
            db.commit()
            return Skill(
                id=cursor.lastrowid,
                name=skill.name,
                description=skill.description,
                content=skill.content,
                license=skill.license,
                compatibility=skill.compatibility,
                metadata=skill.metadata,
                created_at=now,
                updated_at=now,
            )
        else:
            db.execute(
                "UPDATE skills SET name=?, description=?, content=?, license=?, compatibility=?, metadata=?, updated_at=? WHERE id=?",
                (
                    skill.name,
                    skill.description,
                    skill.content,
                    skill.license,
                    skill.compatibility,
                    self._dump_metadata(skill.metadata),
                    now,
                    skill.id,
                ),
            )
            db.commit()
            return Skill(
                id=skill.id,
                name=skill.name,
                description=skill.description,
                content=skill.content,
                license=skill.license,
                compatibility=skill.compatibility,
                metadata=skill.metadata,
                created_at=skill.created_at,
                updated_at=now,
            )

    def upsert(self, skill: Skill) -> Skill:
        db = self._require_db()
        now = format_iso(get_now())
        existing = self.get(skill.name)
        if existing is None:
            cursor = db.execute(
                "INSERT INTO skills (name, description, content, license, compatibility, metadata, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    skill.name,
                    skill.description,
                    skill.content,
                    skill.license,
                    skill.compatibility,
                    self._dump_metadata(skill.metadata),
                    now,
                    now,
                ),
            )
            db.commit()
            return Skill(
                id=cursor.lastrowid,
                name=skill.name,
                description=skill.description,
                content=skill.content,
                license=skill.license,
                compatibility=skill.compatibility,
                metadata=skill.metadata,
                created_at=now,
                updated_at=now,
            )
        else:
            db.execute(
                "UPDATE skills SET description=?, content=?, license=?, compatibility=?, metadata=?, updated_at=? WHERE name=?",
                (
                    skill.description,
                    skill.content,
                    skill.license,
                    skill.compatibility,
                    self._dump_metadata(skill.metadata),
                    now,
                    skill.name,
                ),
            )
            db.commit()
            return Skill(
                id=existing.id,
                name=skill.name,
                description=skill.description,
                content=skill.content,
                license=skill.license,
                compatibility=skill.compatibility,
                metadata=skill.metadata,
                created_at=existing.created_at,
                updated_at=now,
            )

    def delete(self, name: str) -> None:
        if self._db is None:
            return
        self._db.execute("DELETE FROM skills WHERE name = ?", (name,))
        self._db.commit()

    @staticmethod
    def _skill_to_md(skill: Skill) -> str:
        """Serialize a Skill object to SKILL.md format with YAML frontmatter."""
        lines = ["---"]
        lines.append(f"name: {skill.name}")
        if skill.description:
            lines.append(f"description: {skill.description}")
        if skill.license:
            lines.append(f"license: {skill.license}")
        if skill.compatibility:
            lines.append(f"compatibility: {skill.compatibility}")
        if skill.metadata:
            lines.append(f"metadata: {json.dumps(skill.metadata, ensure_ascii=False)}")
        lines.append("---")
        lines.append("")
        lines.append(skill.content)
        return "\n".join(lines)

    def save_to_file(self, skill: Skill, skills_dir: str | None = None) -> Path:
        """Write a single skill to <skills_dir>/<name>/SKILL.md.

        Creates the directory if it doesn't exist.
        Returns the path to the written file.
        """
        if skills_dir is None:
            from nous.config.settings import get_settings

            skills_dir = get_settings().skills_dir
        skill_dir = Path(skills_dir) / skill.name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(self._skill_to_md(skill), encoding="utf-8")
        log = _get_logger()
        log.info("Skill saved to file: %s", skill_file)
        return skill_file

    def delete_from_fs(self, name: str, skills_dir: str | None = None) -> None:
        """Delete a skill directory <skills_dir>/<name>/ recursively."""
        if skills_dir is None:
            from nous.config.settings import get_settings

            skills_dir = get_settings().skills_dir
        skill_dir = Path(skills_dir) / name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
            log = _get_logger()
            log.info("Skill deleted from filesystem: %s", skill_dir)

    def load_from_dir(self, skills_dir: str | None = None, persist: bool = True) -> list[Skill]:
        """Scan <skills_dir>/<name>/SKILL.md files and optionally upsert them into the DB.

        Frontmatter (---block---) may contain `name` and `description` fields.
        The rest of the file becomes the system-prompt `content`.
        If no frontmatter is present the directory name is used as the skill name.

        persist=False: parse files and return Skill objects in-memory without touching the DB.
        Use this for per-persona skills to avoid cross-persona contamination.
        """
        from pathlib import Path

        if skills_dir is None:
            from nous.config.settings import get_settings

            skills_dir = get_settings().skills_dir

        base = Path(skills_dir)
        if not base.exists():
            return []

        result: list[Skill] = []
        for entry in sorted(base.iterdir()):
            if not entry.is_dir():
                continue
            skill_file = entry / "SKILL.md"
            if not skill_file.exists():
                continue
            raw = skill_file.read_text(encoding="utf-8")
            parsed = _parse_skill_md(entry.name, raw)
            # unpack with explicit typing for type checker
            p_name: str = parsed["name"]  # type: ignore[assignment]
            p_desc: str = parsed["description"]  # type: ignore[assignment]
            p_content: str = parsed["content"]  # type: ignore[assignment]
            p_license: str | None = parsed.get("license")  # type: ignore[assignment]
            p_compat: str | None = parsed.get("compatibility")  # type: ignore[assignment]
            p_meta: dict[str, str] | None = parsed.get("metadata")  # type: ignore[assignment]
            skill = Skill(
                name=p_name,
                description=p_desc,
                content=p_content,
                license=p_license,
                compatibility=p_compat,
                metadata=p_meta,
            )
            if persist:
                skill = self.upsert(skill)
            result.append(skill)

        # Cleanup: delete DB skills not present on disk (only when persist=True)
        if persist and result:
            db = self._require_db()
            disk_names = {s.name for s in result}
            db_rows = db.execute("SELECT name FROM skills").fetchall()
            orphan_names = [row[0] for row in db_rows if row[0] not in disk_names]
            if orphan_names:
                placeholders = ",".join("?" * len(orphan_names))
                db.execute(
                    f"DELETE FROM skills WHERE name IN ({placeholders})",  # placeholders only; names bound via params  # nosec B608
                    tuple(orphan_names),
                )
                db.commit()
                log = _get_logger()
                log.info("Cleaned up %d orphaned skills from DB: %s", len(orphan_names), orphan_names)

        return result


def _validate_name(name: str, dir_name: str) -> str:
    """Validate skill name against spec. WARNING on violation, fallback to dir_name."""
    log = _get_logger()
    if not name:
        log.warning("Skill name is empty, using directory name '%s'", dir_name)
        return dir_name
    if len(name) > 64:
        log.warning("Skill name '%s' exceeds 64 chars, using directory name '%s'", name, dir_name)
        return dir_name
    if not _VALID_SKILL_NAME.match(name):
        log.warning(
            "Skill name '%s' invalid (a-z0-9 + hyphens only, no leading/trailing hyphen), using directory name '%s'",
            name,
            dir_name,
        )
        return dir_name
    return name


def _parse_skill_md(dir_name: str, raw: str) -> dict[str, Any]:
    """Extract name/description/license/compatibility/metadata from YAML frontmatter, body as content.

    Returns dict with keys: name, description, content, license, compatibility, metadata.
    """
    name = dir_name
    description = ""
    license_val: str | None = None
    compatibility_val: str | None = None
    metadata_val: dict[str, str] | None = None
    body = raw
    if raw.startswith("---"):
        end = raw.find("---", 3)
        if end != -1:
            fm = raw[3:end].strip()
            body = raw[end + 3 :].strip()
            for line in fm.splitlines():
                stripped = line.strip()
                if stripped.startswith("name:"):
                    name = stripped[5:].strip()
                elif stripped.startswith("description:"):
                    description = stripped[12:].strip()
                elif stripped.startswith("license:"):
                    license_val = stripped[8:].strip()
                elif stripped.startswith("compatibility:"):
                    compatibility_val = stripped[14:].strip()
                elif stripped.startswith("metadata:"):
                    meta_raw = stripped[9:].strip()
                    if meta_raw:
                        try:
                            parsed = json.loads(meta_raw)
                            if isinstance(parsed, dict):
                                metadata_val = {str(k): str(v) for k, v in parsed.items()}
                        except json.JSONDecodeError:
                            log = _get_logger()
                            log.warning("Skill '%s': metadata is not valid JSON, ignoring", name)
    name = _validate_name(name, dir_name)
    return {
        "name": name,
        "description": description,
        "content": body,
        "license": license_val,
        "compatibility": compatibility_val,
        "metadata": metadata_val,
    }
