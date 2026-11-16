"""/api/skills 系ルートのテスト（グローバル + ペルソナの2本読み）。

HTTP サーバーは立てず、``register_skills_routes`` が登録したハンドラを直接呼ぶ。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from nous.api.http.routers import skills as skills_router

pytestmark = pytest.mark.unit


class FakeMCP:
    def __init__(self) -> None:
        self.routes: dict[str, Any] = {}

    def custom_route(self, path: str, methods: list[str]):  # noqa: ARG002
        def register(fn):
            self.routes[path] = fn
            return fn

        return register


def _write_skill(root, name: str, description: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\nbody\n", encoding="utf-8"
    )


@pytest.fixture
def routes(tmp_path, monkeypatch) -> FakeMCP:
    settings = SimpleNamespace(skills_dir=str(tmp_path / "skills"), persona_dir=str(tmp_path / "persona"))
    _write_skill(tmp_path / "skills", "shared", "global version")
    _write_skill(tmp_path / "skills", "only-global", "global only")
    _write_skill(tmp_path / "persona" / "herta" / "skills", "shared", "persona version")

    monkeypatch.setattr("nous.config.settings.get_settings", lambda: settings)
    mcp = FakeMCP()
    skills_router.register_skills_routes(mcp)
    return mcp


def _names(body: bytes) -> dict[str, str]:
    return {item["name"]: item["description"] for item in json.loads(body)}


def _call(handler, persona: str | None):  # noqa: ANN001
    params = {} if persona is None else {"persona": persona}
    return asyncio.run(handler(SimpleNamespace(path_params=params)))


def test_global_list_has_only_global_skills(routes: FakeMCP) -> None:
    res = _call(routes.routes["/api/skills"], None)
    assert _names(res.body) == {"shared": "global version", "only-global": "global only"}


def test_persona_skill_overrides_same_name(routes: FakeMCP) -> None:
    names = _names(_call(routes.routes["/api/skills/{persona}"], "herta").body)
    assert names["shared"] == "persona version"
    assert names["only-global"] == "global only"


@pytest.mark.parametrize("persona", ["../herta", "Herta", ""])
def test_bad_persona_falls_back_to_global(routes: FakeMCP, persona: str) -> None:
    res = _call(routes.routes["/api/skills/{persona}"], persona)
    assert _names(res.body) == {"shared": "global version", "only-global": "global only"}
