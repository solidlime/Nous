"""発動済みスキル（active skills）のセッション別状態管理。

インメモリのみ。再起動・プロセス再生成で失われるが、L1 メタデータは
毎ターン注入されるためモデルが必要に応じて再発動できる。v1 の割り切り。
"""

from __future__ import annotations

from collections import OrderedDict

MAX_ACTIVE_SKILLS = 5
"""1セッションあたりの常駐上限。超過分は最古から外す（文脈爆発防止）。"""

MAX_SESSIONS = 500
"""保持するセッション数の上限。超過分は最古セッションから捨てる。"""

_sessions: OrderedDict[tuple[str, str], list[str]] = OrderedDict()


def _key(persona: str, session_id: str | None) -> tuple[str, str] | None:
    if not session_id:
        return None
    return (persona, session_id)


def get_active(persona: str, session_id: str | None) -> list[str]:
    """発動中スキル名の一覧（発動順）。session_id 不明時は []。"""
    key = _key(persona, session_id)
    if key is None:
        return []
    return list(_sessions.get(key, []))


def activate(persona: str, session_id: str | None, name: str) -> list[str]:
    """スキルを発動状態にする。冪等（再発動は末尾へ移動）。上限超過で最古を外す。"""
    key = _key(persona, session_id)
    if key is None or not name:
        return []
    names = _sessions.pop(key, [])
    if name in names:
        names.remove(name)
    names.append(name)
    del names[: max(0, len(names) - MAX_ACTIVE_SKILLS)]
    _sessions[key] = names
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)
    return list(names)


def deactivate(persona: str, session_id: str | None, name: str) -> list[str]:
    """スキルの発動状態を解除する。存在しなくても冪等に成功する。"""
    key = _key(persona, session_id)
    if key is None or not name:
        return []
    names = _sessions.get(key, [])
    if name in names:
        names = [n for n in names if n != name]
        if names:
            _sessions[key] = names
        else:
            _sessions.pop(key, None)
    return list(names)


def clear_session(persona: str, session_id: str | None) -> None:
    """セッション終了・クリア時に発動状態を捨てる。"""
    key = _key(persona, session_id)
    if key is not None:
        _sessions.pop(key, None)
