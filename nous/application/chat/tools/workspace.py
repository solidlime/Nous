"""ワークスペース境界 — シェル/ファイルツールの唯一の防波堤。

``ToolConfig.workspace_root`` が唯一のルート。未設定ならツール自体が
``get_filtered_tools`` で登録されない。ここは「設定されたが不正」だけを弾く。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nous.config.settings import get_settings
from nous.domain.shared.time_utils import get_now

if TYPE_CHECKING:
    from nous.domain.config.chat_config import ChatConfig


class WorkspaceError(ValueError):
    """ワークスペース未設定・範囲外アクセス。"""


def workspace_root(config: ChatConfig) -> Path:
    """``ToolConfig.workspace_root`` を解決する。不正なら :class:`WorkspaceError`。"""
    raw = (getattr(config, "workspace_root", "") or "").strip()
    if not raw:
        raise WorkspaceError("workspace_root が未設定。設定で作業ディレクトリを指定すること。")
    root = Path(raw).expanduser()
    if not root.is_absolute():
        raise WorkspaceError(f"workspace_root は絶対パスで指定すること: {raw}")
    root = root.resolve()
    if not root.is_dir():
        raise WorkspaceError(f"workspace_root が存在しない: {root}")
    return root


def resolve_in_workspace(root: Path, raw: object) -> Path:
    """ワークスペース配下のパスに解決する。外へ出る指定はすべて拒否（symlink も resolve で潰す）。"""
    text = str(raw or "").strip()
    if not text:
        raise WorkspaceError("path が空")
    given = Path(text).expanduser()
    candidate = (given if given.is_absolute() else root / given).resolve()
    if candidate != root and root not in candidate.parents:
        raise WorkspaceError(f"ワークスペース外は触れない: {text}")
    return candidate


def relative_to_root(root: Path, target: Path) -> str:
    """表示用の相対パス。コンテキストに絶対パスを焼き付けない。"""
    return str(target.relative_to(root)) if target != root else "."


def artifact_path(persona: str, session_id: str | None, tool: str) -> Path:
    """ツール出力の全文を置くパス。会話には末尾だけ載せ、必要なら read_file で読み直させる。"""
    base = Path(get_settings().persona_path(persona)) / "artifacts" / (session_id or "no-session")
    base.mkdir(parents=True, exist_ok=True)
    stamp = get_now().strftime("%Y%m%d-%H%M%S-%f")
    return base / f"{stamp}-{tool}.log"
