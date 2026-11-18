"""ユーザーへのファイル添付 — エージェントが作ったファイルを会話へ渡す。

置き場はユーザー添付と同じ ``persona/{persona}/uploads``。配信は既存の
``GET /api/chat/{persona}/attachment/{filename}`` がそのまま担うので、
新しいルートもサニタイズも増やさない。

sandbox 稼働中はホストのワークスペースが見えない。manager は同じ uploads を
``/home/agent/uploads`` に rw マウントしているので、コピーはコンテナ内で行い、
サイズ検査だけホスト側の実ファイルで行う。
"""

from __future__ import annotations

import contextlib
import mimetypes
import os
import shlex
import shutil
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import quote
from uuid import uuid4

from nous.application.chat.tools.sandbox_shell import resolve_path as sandbox_path
from nous.application.chat.tools.sandbox_shell import sandbox_manager, workspace_path
from nous.application.chat.tools.workspace import WorkspaceError, resolve_in_workspace, workspace_root
from nous.config.settings import get_settings
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
    from nous.domain.config.chat_config import ChatConfig

logger = get_logger(__name__)

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # WebUI の添付上限と揃える
SANDBOX_UPLOADS = "/home/agent/uploads"


class AttachmentError(ValueError):
    """添付できなかった理由。文言はそのまま利用者に見せる。"""


def _unique_path(directory: Path, filename: str) -> Path:
    """同名は ``_1`` 連番で逃がす（ユーザー添付と同じ流儀）。

    shortcut: 存在確認と複製の間に競合の隙がある（同名同時 attach で後勝ち）。
    困るようになったら os.link の EEXIST リトライに変える。
    """
    dest = directory / filename
    counter = 0
    # dangling symlink は exists() が False を通す。辿ると root で任意の場所に書く。
    while dest.exists() or dest.is_symlink():
        counter += 1
        dest = directory / f"{Path(filename).stem}_{counter}{Path(filename).suffix}"
    return dest


def _safe_name(raw: str, fallback: str) -> str:
    """配信ルート（``os.path.basename(...).replace("..", "")``）と同じ規則で名を寝かせる。

    ここで揃えておかないと、``a..b.txt`` のような名前でチップの URL が 404 になる。
    """
    name = os.path.basename(raw).replace("..", "").strip()
    return name or fallback


def _sandbox_source(persona: str, path: str) -> str:
    """コンテナ内のパスをワークスペース配下に限る（``resolve_path`` は ``..`` を拒まない）。"""
    base = workspace_path(persona)
    source = sandbox_path(persona, path)
    if source != base and not source.startswith(base + "/"):
        raise AttachmentError(f"ワークスペース外は触れない: {path}")
    return source


async def _copy_from_sandbox(manager: object, persona: str, path: str, name: str | None) -> Path:
    source = _sandbox_source(persona, path)
    directory = Path(get_settings().persona_uploads_dir(persona))
    directory.mkdir(parents=True, exist_ok=True)
    dest = _unique_path(directory, name or _safe_name(PurePosixPath(source).name, "file"))
    base = workspace_path(persona)
    part_name = f".part-{uuid4().hex[:8]}"
    # 境界検査・サイズ検査・複製をコンテナ内の 1 コマンドに閉じる。
    # readlink -f で symlink を解いた実体を見るので、ワークスペース内の
    # 外差し symlink も抜けない。途中で切れても最終名には書かない（.part 経由）。
    command = (
        f"src=$(readlink -f -- {shlex.quote(source)}) || exit 1; "
        f'case "$src" in {base}/?*) ;; *) exit 3 ;; esac; '
        f'size=$(stat -c %s -- "$src") || exit 1; '
        f'[ "$size" -le {MAX_ATTACHMENT_BYTES} ] || exit 2; '
        f'cp -- "$src" {shlex.quote(f"{SANDBOX_UPLOADS}/{part_name}")} || exit 1; '
        f"mv -f -- {shlex.quote(f'{SANDBOX_UPLOADS}/{part_name}')} "
        f"{shlex.quote(f'{SANDBOX_UPLOADS}/{dest.name}')}"
    )
    try:
        payload = await manager.exec(persona, command)  # type: ignore[attr-defined]
        code = payload.get("exit_code")
        if code is None or payload.get("status") == "error":
            # manager の失敗 payload は message ではなく stderr_tail に理由が入る
            raise AttachmentError(str(payload.get("stderr_tail") or "sandbox でコピーできなかった"))
        if code == 3:
            raise AttachmentError(f"ワークスペース外は触れない: {path}")
        if code == 2:
            raise AttachmentError(f"大きすぎる（上限 {MAX_ATTACHMENT_BYTES // (1024 * 1024)}MB）: {path}")
        if code != 0:
            detail = (payload.get("stderr_tail") or "").strip().splitlines()
            raise AttachmentError(f"コピーできなかった: {detail[0] if detail else 'cp failed'}")
    except BaseException:
        # タイムアウト切断でも部分ファイルを uploads に残さない
        with contextlib.suppress(OSError):
            dest.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            (directory / part_name).unlink(missing_ok=True)
        raise
    # コンテナ内の cp はペルソナ自身の所有になるが、sandbox 無効時に
    # root が作った既存ファイルと同じ扱いに揃えておく。
    with contextlib.suppress(OSError):
        os.chmod(dest, 0o644)
    return dest


def _copy_on_host(config: ChatConfig, persona: str, path: str, name: str | None) -> Path:
    source = resolve_in_workspace(workspace_root(config), path)
    if not source.is_file():
        raise AttachmentError(f"ファイルが無い: {path}")
    if source.stat().st_size > MAX_ATTACHMENT_BYTES:
        raise AttachmentError(f"大きすぎる（上限 {MAX_ATTACHMENT_BYTES // (1024 * 1024)}MB）: {path}")
    if source.is_symlink():
        raise AttachmentError(f"symlink は添付できない: {path}")
    directory = Path(get_settings().persona_uploads_dir(persona))
    directory.mkdir(parents=True, exist_ok=True)
    dest = _unique_path(directory, name or _safe_name(source.name, "file"))
    shutil.copy2(source, dest)
    with contextlib.suppress(OSError):
        os.chmod(dest, 0o644)
    return dest


def _meta(persona: str, dest: Path, caption: str) -> dict:
    mime_type, _ = mimetypes.guess_type(dest.name)
    meta: dict = {
        "filename": dest.name,
        "url": f"/api/chat/{persona}/attachment/{quote(dest.name)}",
        "mime_type": mime_type or "application/octet-stream",
        "size": dest.stat().st_size,
    }
    if caption:
        meta["caption"] = caption
    return meta


async def _handle_attach_file(ctx: AppContext, config: ChatConfig, tool_input: dict) -> dict:
    """ワークスペースのファイルをユーザーに渡す（uploads へ複製）。"""
    path = str(tool_input.get("path") or "").strip()
    if not path:
        return {"status": "error", "message": "path が空"}
    persona = getattr(ctx, "persona", "") or ""
    if not persona:
        return {"status": "error", "message": "persona が未設定"}
    caption = str(tool_input.get("caption") or "").strip()[:200]
    raw_name = str(tool_input.get("name") or "")
    name = _safe_name(raw_name, "") or None

    manager = sandbox_manager(config)
    try:
        if manager is not None:
            dest = await _copy_from_sandbox(manager, persona, path, name)
        else:
            dest = _copy_on_host(config, persona, path, name)
        if dest.stat().st_size > MAX_ATTACHMENT_BYTES:
            dest.unlink(missing_ok=True)
            raise AttachmentError(f"大きすぎる（上限 {MAX_ATTACHMENT_BYTES // (1024 * 1024)}MB）: {path}")
    except (WorkspaceError, AttachmentError) as e:
        return {"status": "error", "message": str(e)}
    except OSError as e:
        logger.warning("attach_file: copy failed", exc_info=True)
        return {"status": "error", "message": f"コピーできなかった: {e}"}

    meta = _meta(persona, dest, caption)
    return {"status": "ok", "attachments": [meta], "message": f"{meta['filename']} を添付した"}
