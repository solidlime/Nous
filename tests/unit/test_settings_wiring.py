"""P7 (v4.0) 設定配線の回帰テスト。

「UI に出るキーは必ずコードから読まれる」を機械的に保証する:

1. ``SessionConfig.model_fields`` の全キーを取得する。
2. リポジトリの ``.py`` / ``.js`` を走査する（下記の設定 UI 受け渡しコードと
   テストは除外。隠しディレクトリ ``.venv`` などの依存も走査しない）。
3. 各キーが 1 箇所以上で参照されていることを assert（違反キーを全列挙）。
4. ``_REMOVED_CONFIG_KEYS_V4`` が (a) ``model_fields`` に無い
   (b) 機能参照として復活していない ことを assert。
5. 設定 UI 受け渡しコードにしか現れないキー（=フロント専用）が、
   実際に DOM 要素を読む JS コンシューマを持つことを assert（evidence 付き）。
6. ``_do_get_config_defaults`` の全フィールドに tier が付くことを assert。

除外集合は「設定 UI の受け渡しコード」であり、そこだけに現れるキーは
未配線とみなす。ただし ``voice_auto_play`` / ``voice_volume`` のように
フロントの音声再生コードが DOM 要素経由で値を読むものは、キー名リテラルが
受け渡しコードにしか現れない。そのため test #5 で「実コンシューマが DOM id を
参照している」ことを追加検証する（コンシューマが消えればテストは赤くなる）。
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from nous.api.http.routers.chat.chat_management import (
    _REMOVED_CONFIG_KEYS_V4,
    _do_get_config_defaults,
)
from nous.domain.session_config import SessionConfig

_REPO_ROOT = Path(__file__).resolve().parents[2]

# 依存・VCS・キャッシュは走査しない（.venv 配下の site-packages を避ける）。
_EXCLUDE_DIR_NAMES = {"node_modules"}
_EXCLUDE_RELATIVE_FILES = {
    "nous/domain/session_config.py",
    "nous/api/http/static/chat/settings/save.js",
    "nous/api/http/static/chat/settings/reset.js",
    "nous/api/http/static/chat/settings/apply.js",
    "nous/api/http/static/chat/settings/apply-groups.js",
}
# 設定 UI の受け渡し / メタデータモジュール。キー名リテラルがここにしか無い
# キーは「機能的な読み手がいない」候補として test #5 で追加検証する。
_SETTINGS_PASSTHROUGH_FILES = _EXCLUDE_RELATIVE_FILES | {
    "nous/api/http/routers/chat/chat_management.py",
}
_SCAN_SUFFIXES = (".py", ".js")

# フロント専用キー → (実際に値を読む JS ファイル, その DOM element id)。
# apply-groups.js が config → DOM 要素を反映し、この JS が要素を読んで再生に使う。
_FRONTEND_DOM_CONSUMED: dict[str, tuple[str, str]] = {
    "voice_auto_play": (
        "nous/api/http/static/chat/send/turn-events.js",
        "chat-voice-auto-play",
    ),
    "voice_volume": (
        "nous/api/http/static/chat/chat-tts.js",
        "chat-voice-volume",
    ),
}


def _is_excluded_dir(rel_parts: tuple[str, ...]) -> bool:
    return any(part in _EXCLUDE_DIR_NAMES or part.startswith(".") for part in rel_parts)


@lru_cache(maxsize=1)
def _scan_texts() -> dict[str, str]:
    """走査対象の .py/.js を (repo 相対パス → 本文) で返す。"""
    texts: dict[str, str] = {}
    for path in _REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(_REPO_ROOT).parts
        if _is_excluded_dir(rel_parts):
            continue
        if path.suffix not in _SCAN_SUFFIXES:
            continue
        rel = "/".join(rel_parts)
        if rel in _EXCLUDE_RELATIVE_FILES or rel.startswith("tests/"):
            continue
        texts[rel] = path.read_text(encoding="utf-8", errors="ignore")
    return texts


_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@lru_cache(maxsize=1)
def _scan_tokens() -> dict[str, frozenset[str]]:
    """走査対象の識別子集合（部分一致誤検出なし・高速）。"""
    return {rel: frozenset(_IDENTIFIER_RE.findall(text)) for rel, text in _scan_texts().items()}


def _referencing_files(key: str) -> list[str]:
    return [rel for rel, tokens in _scan_tokens().items() if key in tokens]


def test_session_config_keys_are_referenced_by_code() -> None:
    """各 SessionConfig キーが受け渡しコード以外の実コードから読まれる。"""
    violations = [name for name in SessionConfig.model_fields if not _referencing_files(name)]
    assert not violations, "未配線の設定キー（UI には出るがコードから読まれていない）: " + ", ".join(sorted(violations))


def test_frontend_dom_consumed_keys_have_a_real_reading_consumer() -> None:
    """受け渡しコードにしか現れないキーは DOM 経由の実コンシューマを要求する。

    test #1 は ``chat_management.py`` の tier/section メタデータのキー名リテラルを
    *参照* として数えてしまう（メタデータは読み手ではない）。ここでは
    受け渡しコード（save/reset/apply/apply-groups.js + chat_management.py +
    session_config.py）以外に参照が無いキーを抽出し、フロント専用として
    DOM コンシューマの存在を検証する。これが無い＝真に死にノブ。
    """
    texts = _scan_texts()
    front_only: list[str] = []
    for name in SessionConfig.model_fields:
        refs = set(_referencing_files(name))
        if refs and not (refs <= _SETTINGS_PASSTHROUGH_FILES):
            continue
        # 受け渡しコード以外のリテラル参照が無い → フロント DOM 経由の消費を要求。
        consumer = _FRONTEND_DOM_CONSUMED.get(name)
        assert consumer is not None, (
            f"未配線の設定キー: {name}（受け渡しコード以外にリテラル参照が無く、DOM コンシューマの登録も無い）"
        )
        consumer_rel, dom_id = consumer
        consumer_text = texts.get(consumer_rel)
        assert consumer_text is not None, f"{name}: コンシューマ {consumer_rel} が存在しない"
        assert dom_id in consumer_text, f"{name}: コンシューマ {consumer_rel} が DOM id {dom_id!r} を参照していない"
        front_only.append(name)
    # 現状のフロント専用キーは音声再生 2 キーのみ。増えたら配線 or 登録を検討する。
    assert set(front_only) == set(_FRONTEND_DOM_CONSUMED), "フロント専用キー集合が想定とずれた: " + ", ".join(
        sorted(front_only)
    )


def test_removed_v4_keys_are_absent() -> None:
    """削除キーが model_fields に無く、機能参照として復活していない。"""
    for name in _REMOVED_CONFIG_KEYS_V4:
        assert name not in SessionConfig.model_fields, f"{name} は v4.0 で削除済み"

    texts = _scan_texts()
    # 例外: chat_management.py の _REMOVED_CONFIG_KEYS_V4 frozenset 定義そのもの。
    # 各キーがこの定義内に 1 回だけ現れることを許し、それ以外の機能参照を禁止する。
    # JS テスト（*.test.js）は「キーが消えたこと」を assert するだけなので
    # 機能参照からは除外する（static/ は別担当領域で変更不可）。
    offenders: list[str] = []
    for name in _REMOVED_CONFIG_KEYS_V4:
        for rel in _referencing_files(name):
            if rel.endswith(".test.js"):
                continue
            text = texts[rel]
            if rel == "nous/api/http/routers/chat/chat_management.py":
                # frozenset 定義の 1 箇所だけを許容（機能参照なら 2 回以上現れる）。
                count = len(re.findall(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text))
                if count <= 1:
                    continue
            offenders.append(f"{rel}:{name}")
    assert not offenders, "削除キーが機能参照として復活している: " + ", ".join(sorted(offenders))


def test_config_defaults_have_tier() -> None:
    """GET config/defaults の全フィールドが basic/advanced/expert を持つ。"""
    fields = _do_get_config_defaults()["fields"]
    assert fields
    missing = [name for name, meta in fields.items() if meta.get("tier") not in {"basic", "advanced", "expert"}]
    assert not missing, "tier 未設定のフィールド: " + ", ".join(sorted(missing))


def test_tier_maps_only_name_real_fields() -> None:
    """_field_tier の明示マップに typo / 廃止キーが混ざっていない。"""
    from nous.api.http.routers.chat.chat_management import _TIER_ADVANCED, _TIER_BASIC
    from nous.domain.chat_config import ChatConfig

    known = set(ChatConfig._all_flat_fields())
    unknown = (_TIER_BASIC | _TIER_ADVANCED) - known
    assert not unknown, "tier マップに未知のキー: " + ", ".join(sorted(unknown))


# ── removed-key compatibility: warn once, ignore value ────────────────


def _install_fake_repo(monkeypatch):
    import types

    from nous.api.http.routers.chat import chat_management as cm
    from nous.domain.chat_config import ChatConfig

    saved: dict[str, object] = {}

    class _FakeRepo:
        def __init__(self, _root: str) -> None:
            pass

        def get(self, persona: str) -> ChatConfig:
            return ChatConfig(persona=persona)

        def save(self, config: ChatConfig) -> None:
            saved["config"] = config

    monkeypatch.setattr(cm, "ChatConfigFileRepository", _FakeRepo)
    monkeypatch.setattr(cm, "get_settings", lambda: types.SimpleNamespace(data_root="/tmp/unused"))
    return saved


def test_save_warns_once_for_removed_v4_keys(monkeypatch, caplog):
    """削除キーを含む保存は 1 リクエスト 1 回 warning を出し、値は無視する。"""
    import asyncio
    import logging

    from nous.api.http.routers.chat import chat_management as cm

    _install_fake_repo(monkeypatch)
    body = {
        "voice_enabled": True,
        "forgetting_trigger_threshold": 50,
        "reflection_threshold": 2.0,
    }

    with caplog.at_level(logging.WARNING):
        result = asyncio.run(cm._do_save_chat_config("p", None, body))

    warnings = [r for r in caplog.records if "ignoring removed v4 config keys" in r.getMessage()]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "forgetting_trigger_threshold" in message
    assert "reflection_threshold" in message
    # 削除キーは保存結果にも現れない（値は無視）
    assert "forgetting_trigger_threshold" not in result
    assert "reflection_threshold" not in result
    assert result["voice_enabled"] is True


def test_save_does_not_warn_without_removed_keys(monkeypatch, caplog):
    """削除キーが無ければ warning は出ない。"""
    import asyncio
    import logging

    from nous.api.http.routers.chat import chat_management as cm

    _install_fake_repo(monkeypatch)
    with caplog.at_level(logging.WARNING):
        asyncio.run(cm._do_save_chat_config("p", None, {"voice_enabled": False}))

    assert not [r for r in caplog.records if "ignoring removed v4 config keys" in r.getMessage()]
