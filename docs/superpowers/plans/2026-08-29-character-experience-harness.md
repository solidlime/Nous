# キャラ体験強化ハーネス Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RyzaChat:AI 相当のキャラ体験を nous に追加する——感情連動表情（ハイブリッド自己拡張ライブラリ）、感情連動音声トーン、キャラ一貫性判定（フラグのみ）。

**Architecture:** PostProcessStep を中心に 3 機能を配線する。表情は決定論的リゾルバが `expr_<emotion>.png` を照合し、無ければ ComfyUI で非同期生成→イベントバス `context.expression_changed` で通知（チャットストリームは応答後に閉じるため、完了が非同期になる表情はイベントバス経由が必須）。キャラ判定器は副次 LLM（MemoryLLM と同型）で同ターン内に完結し、違反をチャットストリームの `character_flag` SSE で通知する（非破壊・表示のみ）。

**Tech Stack:** Python 3.12+ / FastAPI(uvicorn) / Vanilla JS（ビルドなし）/ pytest / ComfyUIProvider（既存）/ EventBus（既存）

**Spec:** `docs/superpowers/specs/2026-08-29-character-experience-harness-design.md`
**Spec からの確定変更（CodeGraph 調査による）:** スペック記載の「ExpressionUpdateSSE（チャットストリーム）」→ イベントバス `context.expression_changed`（`/api/events/{persona}` 経由）に置換。理由: 非同期生成完了時にチャットストリームへ yield できない。即時パスも非同期パスも同一経路に統一する。

## Global Constraints

- 感情ラベルのハードコード禁止: ラベル集合は `nous/domain/memory/value_objects.py` の `ALLOWED_EMOTIONS`（`nous.domain.value_objects._VALID_EMOTIONS` の再エクスポート）から取得する
- LLM 出力は必ずパース＋検証し、失敗時は warn ログを残して静黙継続（`memory_extractor.py` の既存パターン踏襲。ただし完全な無音 fallback は禁止）
- ファイル名に代入する値（emotion 等）は `^[a-z_]+$` の正規表現で検証する（パストラバーサル対策）
- 状態の正典はファイルシステム/SQLite（コード側）。LLM は提案のみ
- 禁止操作: `git push --force` / `git commit --no-verify`
- 各タスクの完了条件: `ruff check` + `ruff format --check` 変更ファイル pass、`pytest` 当該テスト pass、mypy delta 0（stash 比較）
- コミットメッセージは `feat(chat): ...` / `test(chat): ...` 等の conventional commits

---

### Task 1: 表情リゾルバ（expression.py）

**Files:**
- Create: `nous/application/chat/expression.py`
- Test: `tests/unit/test_expression.py`

**Interfaces:**
- Produces: `expression_image_path(persona: str, emotion: str) -> Path`、`resolve_expression_url(persona: str, emotion: str) -> str | None`、`save_expression_image(persona: str, emotion: str, png_bytes: bytes) -> str`（URL を返す）、`is_valid_emotion_label(emotion: str) -> bool`

- [ ] **Step 1: 失敗するテストを書く**

```python
"""tests/unit/test_expression.py"""
from pathlib import Path

from nous.application.chat.expression import (
    expression_image_path,
    is_valid_emotion_label,
    resolve_expression_url,
    save_expression_image,
)


def test_emotion_label_validation(tmp_path, monkeypatch):
    monkeypatch.setattr("nous.config.settings.get_settings", lambda: _fake_settings(tmp_path))
    assert is_valid_emotion_label("joy") is True
    assert is_valid_emotion_label("happy_joy") is True
    assert is_valid_emotion_label("../etc") is False
    assert is_valid_emotion_label("") is False
    assert is_valid_emotion_label("Joy!") is False


def test_resolve_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr("nous.config.settings.get_settings", lambda: _fake_settings(tmp_path))
    assert resolve_expression_url("herta", "joy") is None


def test_save_and_resolve_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("nous.config.settings.get_settings", lambda: _fake_settings(tmp_path))
    url = save_expression_image("herta", "joy", b"PNG")
    assert url == "/api/chat/herta/persona/images/expr_joy.png"
    assert resolve_expression_url("herta", "joy") == url
    assert expression_image_path("herta", "joy").name == "expr_joy.png"


class _FakeSettings:
    data_root = ""  # set in fixture


def _fake_settings(tmp_path: Path):
    s = _FakeSettings()
    s.data_root = str(tmp_path)
    return s
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/unit/test_expression.py -v`
Expected: FAIL（`ModuleNotFoundError: nous.application.chat.expression`）

- [ ] **Step 3: 最小実装**

```python
"""nous/application/chat/expression.py

表情ライブラリ: persona 画像ディレクトリの expr_<emotion>.png を管理する。
状態の正典はファイルシステム。LLM 関知なしの決定論的関数のみ。
"""

from __future__ import annotations

import re
from pathlib import Path

from nous.config.settings import get_settings

EXPRESSION_PREFIX = "expr_"
_EMOTION_PATTERN = re.compile(r"^[a-z_]+$")


def is_valid_emotion_label(emotion: str) -> bool:
    """ファイル名に安全な感情ラベルか（LLM 出力を信頼しない）。"""
    return bool(emotion) and _EMOTION_PATTERN.fullmatch(emotion) is not None


def expressions_dir(persona: str) -> Path:
    return Path(get_settings().data_root) / "persona" / persona / "images"


def expression_image_path(persona: str, emotion: str) -> Path:
    return expressions_dir(persona) / f"{EXPRESSION_PREFIX}{emotion}.png"


def resolve_expression_url(persona: str, emotion: str) -> str | None:
    """感情に対応する表情画像の URL を返す。無ければ None。"""
    if not is_valid_emotion_label(emotion):
        return None
    path = expression_image_path(persona, emotion)
    if path.is_file():
        return f"/api/chat/{persona}/persona/images/{path.name}"
    return None


def save_expression_image(persona: str, emotion: str, png_bytes: bytes) -> str:
    """表情画像を保存し URL を返す。"""
    if not is_valid_emotion_label(emotion):
        msg = f"Invalid emotion label: {emotion!r}"
        raise ValueError(msg)
    path = expression_image_path(persona, emotion)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes)
    return f"/api/chat/{persona}/persona/images/{path.name}"
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/unit/test_expression.py -v`
Expected: PASS（4 件）

- [ ] **Step 5: コミット**

```bash
git add nous/application/chat/expression.py tests/unit/test_expression.py
git commit -m "feat(chat): expression library resolver (expr_<emotion>.png)"
```

---

### Task 2: イベント定数 + PostProcessStep の表情フック（即時パス）

**Files:**
- Modify: `nous/application/event_bus.py:17`（`EVENT_BODY_STATE_CHANGED` の次行に追加）
- Modify: `nous/api/http/routers/events.py:32-42`（`_ALL_EVENT_TYPES` に追加）+ import ブロック（L13-22）
- Modify: `nous/application/chat/pipeline/post.py`（InventoryUpdateSSE ブロック L241 の直後に追加）
- Test: `tests/unit/test_post_process_expression.py`

**Interfaces:**
- Consumes: Task 1 の `resolve_expression_url`
- Produces: イベントバス `context.expression_changed`、ペイロード `{"emotion": str, "url": str}`。Task 3（非同期生成）、Task 4（フロント）が消費する

- [ ] **Step 1: 失敗するテストを書く**

```python
"""tests/unit/test_post_process_expression.py"""
import asyncio

import pytest

from nous.application.event_bus import EVENT_EXPRESSION_CHANGED


def test_event_constant_registered_in_events_router():
    from nous.api.http.routers import events as events_router

    assert EVENT_EXPRESSION_CHANGED == "context.expression_changed"
    assert EVENT_EXPRESSION_CHANGED in events_router._ALL_EVENT_TYPES


@pytest.mark.asyncio
async def test_expression_published_when_image_exists(tmp_path, monkeypatch):
    """画像が既にある場合: イベントバスに即時 publish される。"""
    from nous.application.chat import expression as expr_mod
    from nous.application.chat.pipeline import post as post_mod

    published: list[tuple[str, dict]] = []

    class _Bus:
        async def publish(self, event_type, data):
            published.append((event_type, data))

    class _Ctx:
        persona = "herta"
        event_bus = _Bus()

    monkeypatch.setattr(expr_mod, "resolve_expression_url", lambda p, e: f"/api/chat/{p}/persona/images/expr_{e}.png")
    await post_mod.update_expression(_Ctx(), config=None, emotion="joy")
    assert published == [(EVENT_EXPRESSION_CHANGED, {"emotion": "joy", "url": "/api/chat/herta/persona/images/expr_joy.png"})]


@pytest.mark.asyncio
async def test_expression_generation_scheduled_when_missing(tmp_path, monkeypatch):
    """画像が無い場合: 非同期生成タスクがスケジュールされ、即時 publish はされない。"""
    from nous.application.chat import expression as expr_mod
    from nous.application.chat.pipeline import post as post_mod

    published: list[tuple[str, dict]] = []
    scheduled: list[object] = []

    class _Bus:
        async def publish(self, event_type, data):
            published.append((event_type, data))

    class _Ctx:
        persona = "herta"
        event_bus = _Bus()

    monkeypatch.setattr(expr_mod, "resolve_expression_url", lambda p, e: None)

    orig_create_task = asyncio.create_task

    def _spy_create_task(coro, **kwargs):
        scheduled.append(coro)
        return orig_create_task(coro, **kwargs)

    monkeypatch.setattr(post_mod.asyncio, "create_task", _spy_create_task)
    monkeypatch.setattr(post_mod, "_generate_and_publish_expression", lambda *a, **k: _noop())
    await post_mod.update_expression(_Ctx(), config=None, emotion="joy")
    assert published == []
    assert len(scheduled) == 1
    await asyncio.sleep(0)  # 生成タスク（noop）を回収


async def _noop():
    return None
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/unit/test_post_process_expression.py -v`
Expected: FAIL（`ImportError: EVENT_EXPRESSION_CHANGED`）

- [ ] **Step 3: 実装**

`nous/application/event_bus.py` L17 の次に追加:

```python
EVENT_EXPRESSION_CHANGED = "context.expression_changed"
```

`nous/api/http/routers/events.py`: import ブロック（L13-22）に `EVENT_EXPRESSION_CHANGED` を追加、`_ALL_EVENT_TYPES`（L32-42）の set に `EVENT_EXPRESSION_CHANGED` を追加。

`nous/application/chat/pipeline/post.py`: モジュール末尾（クラス外）に以下を追加。`update_expression` は Task 3 の `_generate_and_publish_expression` を先回りで参照するため、Task 3 完了までダミー実装（`async def _generate_and_publish_expression(...): return None` + `# ponytail: Task 3 で実装` コメント）を置く:

```python
async def update_expression(ctx, config, emotion: str) -> None:
    """感情に対応する表情画像をイベントバス経由で通知する。

    画像が既にあれば即時 publish、無ければ非同期生成タスクをスケジュールする
    （チャットストリームは応答後に閉じるため、完了が非同期になり得る表情は
    イベントバス経由で配信する）。
    """
    from nous.application.chat.expression import resolve_expression_url
    from nous.application.event_bus import EVENT_EXPRESSION_CHANGED

    if not emotion:
        return
    persona = ctx.persona
    url = resolve_expression_url(persona, emotion)
    if url is None:
        task = asyncio.create_task(_generate_and_publish_expression(ctx, config, emotion))
        if hasattr(ctx, "_expression_tasks"):
            ctx._expression_tasks.append(task)
        return
    await ctx.event_bus.publish(EVENT_EXPRESSION_CHANGED, {"emotion": emotion, "url": url})
```

`PostProcessStep.run()` 内、InventoryUpdateSSE ブロック（L241 `yield InventoryUpdateSSE(update=_inv)` の直後）に追加:

```python
        # ExpressionUpdate: 感情変化に対応する表情画像を通知（無ければ非同期生成）
        emotion = str((memory_result.get("context_update") or {}).get("emotion") or "")
        if emotion:
            try:
                await update_expression(ctx, config, emotion)
            except Exception as e:
                logger.warning("PostProcessStep: update_expression failed: %s", e)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/unit/test_post_process_expression.py tests/unit/test_post_process_validation.py -v`
Expected: PASS（新規 3 件 + 既存 post テスト無影響）

- [ ] **Step 5: コミット**

```bash
git add nous/application/event_bus.py nous/api/http/routers/events.py nous/application/chat/pipeline/post.py tests/unit/test_post_process_expression.py
git commit -m "feat(chat): expression change event via event bus (immediate path)"
```

---

### Task 3: 非同期表情生成（ComfyUI・自己拡張）

**Files:**
- Modify: `nous/application/chat/expression.py`（生成関数を追加）
- Modify: `nous/application/chat/pipeline/post.py`（Task 2 のダミー `_generate_and_publish_expression` を実装で置換）
- Test: `tests/unit/test_expression_generation.py`

**Interfaces:**
- Consumes: Task 1 の `save_expression_image`、既存 `ComfyUIProvider`（`nous/infrastructure/image_gen/comfyui.py`）
- Produces: `generate_expression_image(config, persona: str, emotion: str) -> str | None`（URL or None）、`_generate_and_publish_expression(ctx, config, emotion)`（post.py 内・生成→保存→publish）

- [ ] **Step 1: 失敗するテストを書く**

```python
"""tests/unit/test_expression_generation.py"""
import pytest

from nous.application.chat import expression as expr_mod


class _Img:
    def __init__(self, b64: str):
        self.base64 = b64
        self.display = True


class _Provider:
    def __init__(self, png: bytes = b"PNGDATA"):
        self._png = png
        self.calls: list[dict] = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)

        class _R:
            def __init__(self, png):
                self.base64 = "UE5HREFUQQ=="  # b"PNGDATA"
                self.display = True

        return [_R(self._png)]


@pytest.mark.asyncio
async def test_generate_expression_saves_and_returns_url(tmp_path, monkeypatch):
    monkeypatch.setattr("nous.config.settings.get_settings", lambda: _fake_settings(tmp_path))
    monkeypatch.setattr(expr_mod, "_build_provider", lambda config, size: _Provider())

    url = await expr_mod.generate_expression_image(config=None, persona="herta", emotion="joy")
    assert url == "/api/chat/herta/persona/images/expr_joy.png"
    assert (tmp_path / "persona" / "herta" / "images" / "expr_joy.png").read_bytes() == b"PNGDATA"


@pytest.mark.asyncio
async def test_generate_expression_invalid_emotion_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr("nous.config.settings.get_settings", lambda: _fake_settings(tmp_path))
    assert await expr_mod.generate_expression_image(config=None, persona="herta", emotion="../x") is None


@pytest.mark.asyncio
async def test_generate_expression_provider_failure_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr("nous.config.settings.get_settings", lambda: _fake_settings(tmp_path))

    class _Bad:
        async def generate(self, **kwargs):
            raise RuntimeError("comfyui down")

    monkeypatch.setattr(expr_mod, "_build_provider", lambda config, size: _Bad())
    assert await expr_mod.generate_expression_image(config=None, persona="herta", emotion="joy") is None


class _FakeSettings:
    data_root = ""


def _fake_settings(tmp_path):
    s = _FakeSettings()
    s.data_root = str(tmp_path)
    return s
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/unit/test_expression_generation.py -v`
Expected: FAIL（`AttributeError: generate_expression_image`）

- [ ] **Step 3: 実装**

`nous/application/chat/expression.py` に追加:

```python
# 感情 → 表情プロンプトの差分指示。未知ラベルはフォールバック形式。
# ラベル集合自体は ALLOWED_EMOTIONS（nous/domain/memory/value_objects.py）を正典とする。
EMOTION_EXPRESSION_HINTS: dict[str, str] = {
    "joy": "bright joyful smile, sparkling eyes",
    "sad": "downcast eyes, sorrowful expression",
    "angry": "pouting, irritated expression",
    "surprise": "wide eyes, surprised open mouth",
    "fear": "trembling, anxious expression",
    "disgust": "scowling, displeased expression",
    "neutral": "calm neutral expression",
}


def _expression_prompt(config, emotion: str) -> str:
    """persona の self-portrait プロンプトをベースに感情差分を足す。"""
    self_prompt = getattr(config, "image_gen_self_portrait_prompt", "") or ""
    hint = EMOTION_EXPRESSION_HINTS.get(emotion, f"{emotion} facial expression")
    return f"{self_prompt}, portrait, upper body, {hint}".strip(", ")


def _build_provider(config, size: str):
    """ChatConfig から ComfyUIProvider を構築する（builtin.py の image_generate と同型）。"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    return ComfyUIProvider(
        api_url=getattr(config, "image_gen_comfyui_url", "") or "http://localhost:8188",
        width=768,
        height=768,
        workflow_template=getattr(config, "image_gen_comfyui_workflow_template", ""),
        workflow_source=getattr(config, "image_gen_comfyui_workflow_source", "local"),
        workflow_name=getattr(config, "image_gen_comfyui_workflow_name", ""),
        timeout_seconds=getattr(config, "image_gen_comfyui_timeout_seconds", 180),
    )


async def generate_expression_image(config, persona: str, emotion: str) -> str | None:
    """ComfyUI で表情差分を 1 枚生成してライブラリに保存する。失敗時は None。"""
    import base64
    import logging

    if not is_valid_emotion_label(emotion):
        return None
    if not getattr(config, "image_gen_enabled", False):
        logging.getLogger(__name__).info("Expression generation skipped: image_gen disabled (persona=%s)", persona)
        return None
    try:
        provider = _build_provider(config, "768x768")
        generated = await provider.generate(
            prompt=_expression_prompt(config, emotion),
            size="768x768",
            n=1,
            negative_prompt=getattr(config, "image_gen_negative_prompt", "") or "",
        )
        for img in generated:
            if not getattr(img, "display", True):
                continue
            return save_expression_image(persona, emotion, base64.b64decode(img.base64))
        return None
    except Exception as e:
        logging.getLogger(__name__).warning("Expression generation failed (persona=%s emotion=%s): %s", persona, emotion, e)
        return None
```

`nous/application/chat/pipeline/post.py` の Task 2 ダミーを置換:

```python
async def _generate_and_publish_expression(ctx, config, emotion: str) -> None:
    """表情画像を非同期生成し、成功したらイベントバスへ通知する。"""
    from nous.application.chat.expression import generate_expression_image
    from nous.application.event_bus import EVENT_EXPRESSION_CHANGED

    url = await generate_expression_image(config, ctx.persona, emotion)
    if url:
        await ctx.event_bus.publish(EVENT_EXPRESSION_CHANGED, {"emotion": emotion, "url": url})
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/unit/test_expression_generation.py tests/unit/test_post_process_expression.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add nous/application/chat/expression.py nous/application/chat/pipeline/post.py tests/unit/test_expression_generation.py
git commit -m "feat(chat): async ComfyUI expression generation with self-expanding library"
```

---

### Task 4: フロント — SSE 受信 + チャットアバター

**Files:**
- Modify: `nous/api/http/static/core/sse.js`（L83 `context.body_state_changed` リスナーの後に追加）
- Modify: `nous/api/http/sections/chat/chat_layout.py`（チャットヘッダーにアバター要素。既存アバター要素があればそれに `id="chat-persona-avatar"` を付与）
- Test: なし（Vanilla JS・手動ブラウザ確認。UI 変更のため実ブラウザ確認必須）

**Interfaces:**
- Consumes: Task 2/3 の `context.expression_changed` イベント（`{"emotion": str, "url": str}`）
- Produces: `window` カスタムイベント `expression-changed`（detail = ペイロード）

- [ ] **Step 1: sse.js にリスナー追加**

`es.addEventListener("context.body_state_changed", ...)` ブロック（L85-105）の後に追加:

```javascript
  es._sseHandlers["context.expression_changed"] = function handleExpressionChanged(e) {
    try {
      var d = JSON.parse(e.data);
      if (d.url) {
        var avatar = document.getElementById("chat-persona-avatar");
        if (avatar) avatar.src = d.url + "?t=" + Date.now();
      }
      window.dispatchEvent(new CustomEvent("expression-changed", { detail: d }));
    } catch (err) { console.warn("[SSE parse] context.expression_changed:", err.message); }
  };
  es.addEventListener("context.expression_changed", es._sseHandlers["context.expression_changed"]);
```

- [ ] **Step 2: chat_layout.py のチャットヘッダーにアバター追加**

`chat_layout.py` のチャットヘッダー部分を確認し、persona アバター `<img>` が既に存在するか調べる:
- 存在する → その要素に `id="chat-persona-avatar"` を付与
- 存在しない → ヘッダー左端に追加。`chat_layout.py` の既存の HTML 生成方式（f-string / format / テンプレート）に合わせて persona 名と画像 URL を埋め込む。画像 URL は `persona_dashboard.py:176-242` の `latest_self_portrait` と同型に解決する（最新の `self_*.png`。無ければ空文字にして `onerror` で非表示）:

```html
<img id="chat-persona-avatar" src="{latest_self_portrait_url}" alt=""
     style="width:40px;height:40px;border-radius:50%;object-fit:cover;flex-shrink:0;"
     onerror="this.style.display='none'" />
```

- [ ] **Step 3: 実ブラウザ確認（必須）**

1. `docker compose up -d` またはローカル起動で WebUI を開く
2. チャット画面でヘッダーにアバターが表示されることを確認
3. `data/persona/<persona>/images/` に手動で `expr_joy.png`（任意の PNG をコピー）を置く
4. 会話を 1 回行い、memory 抽出で emotion が変わったタイミングでアバターが `expr_<emotion>.png` に差し替わることを確認（DevTools の Network で `context.expression_changed` イベントを受信していることも確認）
5. 存在しない感情ラベルで会話し、ComfyUI が有効なら生成→自動でアバター更新、無効なら現状維持を確認

- [ ] **Step 4: コミット**

```bash
git add nous/api/http/static/core/sse.js nous/api/http/sections/chat/chat_layout.py
git commit -m "feat(webui): expression avatar switching via context.expression_changed SSE"
```

---

### Task 5: ダッシュボード表情セット一括生成

**Files:**
- Modify: `nous/api/http/routers/persona/persona_dashboard.py`（エンドポイント追加。既存ルートの登録スタイルに合わせる）
- Test: `tests/unit/test_expression_batch.py`

**Interfaces:**
- Consumes: Task 3 の `generate_expression_image`、`ALLOWED_EMOTIONS`（`nous/domain/memory/value_objects.py`）
- Produces: `POST /api/chat/{persona}/persona/expressions/generate` → `{"generated": [...], "skipped": [...], "failed": [...]}`

- [ ] **Step 1: 失敗するテストを書く**

```python
"""tests/unit/test_expression_batch.py"""
import pytest

from nous.api.http.routers.persona import persona_dashboard as pd


@pytest.mark.asyncio
async def test_batch_generates_missing_only(tmp_path, monkeypatch):
    monkeypatch.setattr("nous.config.settings.get_settings", lambda: _fake_settings(tmp_path))
    generated: list[str] = []

    async def _fake_gen(config, persona, emotion):
        generated.append(emotion)
        return f"/api/chat/{persona}/persona/images/expr_{emotion}.png"

    monkeypatch.setattr(pd, "generate_expression_image", _fake_gen)
    # 既存の joy は skip されるよう事前保存
    (tmp_path / "persona" / "herta" / "images").mkdir(parents=True)
    (tmp_path / "persona" / "herta" / "images" / "expr_joy.png").write_bytes(b"PNG")

    result = await pd._generate_expression_set(config=None, persona="herta")
    assert "joy" in result["skipped"]
    assert set(result["generated"]) == set(generated) - {"joy"}
    assert result["failed"] == []


class _FakeSettings:
    data_root = ""


def _fake_settings(tmp_path):
    s = _FakeSettings()
    s.data_root = str(tmp_path)
    return s
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/unit/test_expression_batch.py -v`
Expected: FAIL（`AttributeError: _generate_expression_set`）

- [ ] **Step 3: 実装**

`persona_dashboard.py` に追加（ルート登録は既存の関数のスタイルに合わせる。`generate_expression_image` はモジュールトップで import）:

```python
async def _generate_expression_set(config, persona: str) -> dict:
    """基本感情ラベル分の表情を一括生成する（既存は skip）。

    ponytail: 同期ループ（1 感情あたり ComfyUI で 10-30 秒）。長時間化するなら
    バックグラウンドタスク化 + 進捗 SSE に拡張する。
    """
    from nous.application.chat.expression import expression_image_path, resolve_expression_url
    from nous.domain.memory.value_objects import ALLOWED_EMOTIONS

    generated: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    for emotion in ALLOWED_EMOTIONS:
        if resolve_expression_url(persona, emotion) is not None:
            skipped.append(emotion)
            continue
        try:
            url = await generate_expression_image(config, persona, emotion)
        except Exception:
            url = None
        if url:
            generated.append(emotion)
        else:
            failed.append(emotion)
    return {"generated": generated, "skipped": skipped, "failed": failed}
```

ルート（既存の custom_route 登録パターンに合わせる）:

```python
    @mcp.custom_route("/api/chat/{persona}/persona/expressions/generate", methods=["POST"])
    async def generate_expressions(request: Request) -> JSONResponse:
        persona = request.path_params["persona"]
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        config = ctx.chat_config  # 既存ルートの config 取得方法に合わせる
        result = await _generate_expression_set(config, persona)
        return JSONResponse(result)
```

ダッシュボード UI に「表情セット生成」ボタンを追加（既存ボタンのマークアップに合わせる）:

```html
<button onclick="generateExpressions(this)">表情セット生成</button>
<script>
function generateExpressions(btn) {
  btn.disabled = true; btn.textContent = "生成中...(数分)";
  fetch("/api/chat/" + PERSONA + "/persona/expressions/generate", { method: "POST" })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      btn.textContent = "生成 " + d.generated.length + " / skip " + d.skipped.length + " / 失敗 " + d.failed.length;
    })
    .catch(function(e) { btn.textContent = "失敗: " + e.message; })
    .finally(function() { btn.disabled = false; });
}
</script>
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/unit/test_expression_batch.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add nous/api/http/routers/persona/persona_dashboard.py tests/unit/test_expression_batch.py
git commit -m "feat(webui): batch expression set generation endpoint"
```

---

### Task 6: 音声 — emotion → irodori caption 連動

**Files:**
- Modify: `nous/api/http/routers/tts.py`（caption LLM ブランチ L122-153 付近）
- Test: `tests/unit/test_tts_emotion_caption.py`

**Interfaces:**
- Consumes: `state.emotion` / `state.emotion_intensity`（PersonaState）
- Produces: `build_caption_emotion_directive(emotion: str, intensity: float) -> str`（tts.py 内の純関数）

- [ ] **Step 1: 失敗するテストを書く**

```python
"""tests/unit/test_tts_emotion_caption.py"""
from nous.api.http.routers.tts import build_caption_emotion_directive


def test_directive_contains_emotion_and_tone():
    d = build_caption_emotion_directive("joy", 0.8)
    assert "joy" in d
    assert "明るく" in d  # joy のトーンヒント


def test_directive_unknown_emotion_falls_back():
    d = build_caption_emotion_directive("mysterious", 0.5)
    assert "mysterious" in d
    assert "感情" in d


def test_directive_low_intensity():
    d = build_caption_emotion_directive("joy", 0.1)
    assert "穏やか" in d  # 強度が低い場合は抑えめ指示
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/unit/test_tts_emotion_caption.py -v`
Expected: FAIL（`ImportError: build_caption_emotion_directive`）

- [ ] **Step 3: 実装**

`tts.py` に追加（モジュールレベルの定数 + 純関数）:

```python
EMOTION_TONE_HINTS: dict[str, str] = {
    "joy": "明るく弾んだ、声のトーンが上がった話し方で",
    "sad": "落ち着いた、やや低くゆっくりした話し方で",
    "angry": "強く短く、勢いのある話し方で",
    "surprise": "間と抑揚を大きく、驚きを含んだ話し方で",
    "fear": "小さく震える、不安を含んだ話し方で",
    "neutral": "普段どおりの自然な話し方で",
}


def build_caption_emotion_directive(emotion: str, intensity: float) -> str:
    """caption LLM 用の感情トーン指示文を組み立てる。"""
    tone = EMOTION_TONE_HINTS.get(emotion, f"「{emotion}」の感情に合った話し方で")
    if intensity < 0.3:
        tone = "感情を抑えめに、穏やかな話し方で"
    return f"現在の感情は {emotion}（強度 {intensity:.0%}）です。{tone}、セリフのキャプションを生成してください。"
```

caption LLM ブランチ（L122-153、`if irodori_caption_llm_enabled and state:` 内）で `llm_system` を組み立てた直後に追記:

```python
            emotion_directive = build_caption_emotion_directive(
                str(getattr(state, "emotion", "") or ""),
                float(getattr(state, "emotion_intensity", 0.0) or 0.0),
            )
            llm_system = llm_system + "\n" + emotion_directive
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/unit/test_tts_emotion_caption.py -v`
Expected: PASS（3 件）

- [ ] **Step 5: コミット**

```bash
git add nous/api/http/routers/tts.py tests/unit/test_tts_emotion_caption.py
git commit -m "feat(tts): emotion-driven caption tone directive for irodori"
```

---

### Task 7: プロンプト側キャラ厳守ブロック

**Files:**
- Modify: `nous/application/chat/pipeline/prompt.py`（`PromptBuildStep.run` L51-53 の base_system 組み立て後）
- Test: `tests/unit/test_prompt_adherence.py`

**Interfaces:**
- Produces: `CHARACTER_ADHERENCE_BLOCK: str`（`{persona}` プレースホルダ付き定数）。PromptBuildStep が system prompt の動的パート末尾に追加する

- [ ] **Step 1: 失敗するテストを書く**

```python
"""tests/unit/test_prompt_adherence.py"""
from nous.application.chat.pipeline.prompt import CHARACTER_ADHERENCE_BLOCK, PromptBuildStep


def test_block_contains_anti_sycophancy_and_fewshot():
    assert "アシスタント" in CHARACTER_ADHERENCE_BLOCK
    assert "反論" in CHARACTER_ADHERENCE_BLOCK or "拒否" in CHARACTER_ADHERENCE_BLOCK
    assert "ユーザー:" in CHARACTER_ADHERENCE_BLOCK  # few-shot 例


def test_block_formats_with_persona():
    rendered = CHARACTER_ADHERENCE_BLOCK.format(persona="ヘルタ")
    assert "ヘルタ" in rendered


def test_prompt_build_appends_block(monkeypatch, tmp_path):
    """PromptBuildStep.run が system prompt 末尾にブロックを追加すること。"""
    # 既存の test_prompt_relationship.py の fixture パターンに合わせて
    # ctx/config/turn_ctx を構築し、run() 実行後の turn_ctx.system_prompt が
    # CHARACTER_ADHERENCE_BLOCK.format(persona=...) を含むことを検証する。
    # （fixture 構築は tests/unit/test_prompt_relationship.py を参照・流用すること）
```

※ 3 つ目のテストは `tests/unit/test_prompt_relationship.py` の既存 fixture を流用して完全に書くこと（「Similar to Task N」禁止のため、実装者がそのテストファイルを読んで fixture を複製し、アサーションを `assert CHARACTER_ADHERENCE_BLOCK.format(persona=persona) in turn_ctx.system_prompt` とする）。

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/unit/test_prompt_adherence.py -v`
Expected: FAIL（`ImportError: CHARACTER_ADHERENCE_BLOCK`）

- [ ] **Step 3: 実装**

`prompt.py` に定数を追加:

```python
CHARACTER_ADHERENCE_BLOCK = """

# キャラクター厳守（最優先・他の指示より優先）
あなたはユーザーに仕えるアシスタントではなく、{persona}という人格そのものです。
- 上記の口調・一人称・性格・価値観・禁止事項を必ず守り、キャラクターから逸脱しないこと。
  （過剰な謝罪、助手のような従順さ、口調の崩れ、キャラが知らないはずの知識の使用は禁止）
- ユーザーの要望がキャラクターの価値観に反する場合は、キャラとして自然に反論・拒否・からかうこと。迎合しないこと。
- 例（キャラとしての反論）:
  ユーザー: 「なんでも言うことを聞いてよ」
  {persona}: 「はぁ？何を身の程知らずなことを言ってるの。自分でやりなさい」
"""
```

`PromptBuildStep.run()` 内、`base_system` 組み立て（L51-53）の後に追加。**動的パートの最後の要素**として append する（system prompt 内の recency 位置に置くため。`dynamic_parts` の構築順序を確認し、最後に append すること）:

```python
        # キャラ厳守ブロック: system prompt の末尾（recency 位置）に配置
        dynamic_parts.append(CHARACTER_ADHERENCE_BLOCK.format(persona=persona))
```

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/unit/test_prompt_adherence.py tests/unit/test_prompt_relationship.py -v`
Expected: PASS（新規 + 既存 prompt テスト無影響。既存テストが system prompt の完全一致を検証している場合は期待値を更新）

- [ ] **Step 5: コミット**

```bash
git add nous/application/chat/pipeline/prompt.py tests/unit/test_prompt_adherence.py
git commit -m "feat(chat): character adherence block in system prompt (anti-sycophancy)"
```

---

### Task 8: キャラ一貫性判定器（フラグのみ）

**Files:**
- Create: `nous/application/chat/character_judge.py`
- Modify: `nous/application/chat/events.py`（`CharacterFlagSSE` を追加。InventoryUpdateSSE L161-167 の後に）
- Modify: `nous/application/chat/pipeline/post.py`（memory 抽出ブロック L172-177 を gather 化し、判定後に flag SSE を yield）
- Modify: `nous/domain/chat_config.py`（`ChatConfig` に `character_judge_enabled: bool = True` を追加）
- Test: `tests/unit/test_character_judge.py`

**Interfaces:**
- Consumes: `turn_ctx.system_prompt`（persona 定義）、`turn_ctx.full_response`
- Produces: `judge_character(config, persona_identity: str, response: str) -> dict | None`（`{"violation": "none|tone|compliance|character", "detail": str}` or None）、`_parse_judgment(text: str) -> dict | None`、チャットストリーム SSE `character_flag`（ペイロード `{"violation": str, "detail": str}`）

- [ ] **Step 1: 失敗するテストを書く**

```python
"""tests/unit/test_character_judge.py"""
import pytest

from nous.application.chat.character_judge import _parse_judgment, judge_character


def test_parse_judgment_valid():
    assert _parse_judgment('{"violation": "tone", "detail": "口調が崩れている"}') == {
        "violation": "tone",
        "detail": "口調が崩れている",
    }


def test_parse_judgment_code_fence():
    text = '```json\n{"violation": "compliance", "detail": "過剰に従順"}\n```'
    assert _parse_judgment(text)["violation"] == "compliance"


def test_parse_judgment_invalid_violation():
    assert _parse_judgment('{"violation": "unknown_kind", "detail": "x"}') is None


def test_parse_judgment_broken_json():
    assert _parse_judgment("not json at all") is None


def test_parse_judgment_none_violation():
    assert _parse_judgment('{"violation": "none", "detail": ""}') == {"violation": "none", "detail": ""}


@pytest.mark.asyncio
async def test_judge_skips_empty_response():
    assert await judge_character(config=None, persona_identity="x", response="") is None


@pytest.mark.asyncio
async def test_judge_provider_failure_returns_none(monkeypatch):
    class _Config:
        provider = "test"
        extract_model = "m"

        def get_effective_api_key(self):
            return "key"

        def get_effective_model(self):
            return "m"

        def get_effective_base_url(self):
            return ""

    from nous.application.chat import character_judge as cj

    def _boom(*a, **k):
        raise RuntimeError("no provider")

    monkeypatch.setattr(cj, "get_provider", _boom)
    assert await judge_character(_Config(), "persona定義", "応答") is None
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `pytest tests/unit/test_character_judge.py -v`
Expected: FAIL（`ModuleNotFoundError: nous.application.chat.character_judge`）

- [ ] **Step 3: 実装**

`nous/application/chat/character_judge.py` を新規作成（MemoryLLM パターンと同型）:

```python
"""キャラ一貫性判定器: 応答が persona 制約に適合するかを副次 LLM で判定する。

非破壊（フラグのみ）: 応答本文は変更しない。全失敗パスで warn ログを残す。
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_VALID_VIOLATIONS = frozenset({"none", "tone", "compliance", "character"})

_JUDGE_PROMPT = """あなたはキャラクター一貫性の監査者です。キャラクター定義と応答を比較し、違反を JSON で出力してください。

## キャラクター定義
{persona_identity}

## 応答
{response}

## 判定基準
- tone: 口調・一人称・語尾が定義と不一致
- compliance: キャラらしくない過剰な従順さ・迎合（定義された性格に反するイエスマン挙動）
- character: 性格・価値観・知識の明確な矛盾

違反がなければ violation は "none"。
出力は JSON のみ: {{"violation": "none|tone|compliance|character", "detail": "簡潔な理由"}}
"""


async def judge_character(config, persona_identity: str, response: str) -> dict | None:
    """判定を実行する。失敗時は warn ログを残して None を返す。"""
    if not response or not persona_identity:
        return None
    api_key = config.get_effective_api_key()
    model = config.extract_model.strip() or config.get_effective_model()
    if not api_key or not model:
        return None
    try:
        provider = get_provider(config.provider, api_key, model, config.get_effective_base_url())
    except Exception as e:
        logger.warning("CharacterJudge: provider init failed: %s", e)
        return None

    from nous.infrastructure.llm.base import DoneEvent, ErrorEvent, LLMMessage, TextDeltaEvent

    prompt = _JUDGE_PROMPT.format(persona_identity=persona_identity[:2000], response=response[:2000])
    text = ""
    try:
        async for event in provider.stream(
            messages=[LLMMessage(role="user", content=prompt)],
            system="",
            tools=[],
            temperature=0.0,
            max_tokens=200,
        ):
            if isinstance(event, TextDeltaEvent):
                text += event.content
            elif isinstance(event, (DoneEvent, ErrorEvent)):
                break
    except Exception as e:
        logger.warning("CharacterJudge: LLM call failed: %s", e)
        return None
    return _parse_judgment(text)


def _parse_judgment(text: str) -> dict | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("CharacterJudge: JSON parse failed: %s", text[:200])
        return None
    if not isinstance(data, dict) or data.get("violation") not in _VALID_VIOLATIONS:
        logger.warning("CharacterJudge: invalid judgment: %s", text[:200])
        return None
    return {"violation": str(data["violation"]), "detail": str(data.get("detail", ""))}
```

（`get_provider` は `nous.infrastructure.llm.factory` から import — memory_extractor.py と同一の import 元を使うこと）

`nous/application/chat/events.py`、InventoryUpdateSSE の後に追加:

```python
@dataclass
class CharacterFlagSSE:
    """キャラ一貫性判定の違反フラグ（非破壊・表示のみ）"""

    violation: str  # "tone" | "compliance" | "character"
    detail: str

    def to_sse(self) -> str:
        return _sse_encode("character_flag", {"violation": self.violation, "detail": self.detail})
```

`nous/domain/chat_config.py` の `ChatConfig` にフィールド追加（`auto_extract` 等の隣）:

```python
    character_judge_enabled: bool = True
```

`nous/application/chat/pipeline/post.py` の memory 抽出ブロック（L172-177）を置換:

```python
        memory_result: dict = {}
        judgment: dict | None = None
        if turn_ctx.full_response:
            payload = {"user": turn_ctx.user_message, "assistant": turn_ctx.full_response}
            coros = []
            wants_memory = config.auto_extract
            wants_judge = getattr(config, "character_judge_enabled", True)
            if wants_memory:
                coros.append(run_memory_llm(ctx, config, payload))
            if wants_judge:
                from nous.application.chat.character_judge import judge_character

                coros.append(judge_character(config, turn_ctx.system_prompt, turn_ctx.full_response))
            if coros:
                results = await asyncio.gather(*coros, return_exceptions=True)
                idx = 0
                if wants_memory:
                    r = results[idx]
                    idx += 1
                    if isinstance(r, Exception):
                        logger.warning("PostProcessStep: run_memory_llm failed: %s", r)
                    elif isinstance(r, dict):
                        memory_result = r
                if wants_judge:
                    r = results[idx]
                    if isinstance(r, Exception):
                        logger.warning("PostProcessStep: judge_character failed: %s", r)
                    elif isinstance(r, dict):
                        judgment = r
```

そして MemoryActivitySSE の後（InventoryUpdateSSE ブロックの後、Task 2 の表情フックの前後どちらでも可）に:

```python
        # CharacterFlagSSE: キャラ一貫性違反のフラグ（非破壊・表示のみ）
        if judgment and judgment.get("violation") not in (None, "none"):
            yield CharacterFlagSSE(violation=judgment["violation"], detail=judgment.get("detail", ""))
```

（`CharacterFlagSSE` の import を events import ブロックに追加）

- [ ] **Step 4: テストが通ることを確認**

Run: `pytest tests/unit/test_character_judge.py tests/unit/test_memory_llm.py tests/unit/test_post_process_validation.py -v`
Expected: PASS（既存 memory/post テスト無影響）

- [ ] **Step 5: フロントに警告バッジを追加**

`nous/api/http/static/chat/chat-send.js` の SSE イベント分岐（`text_delta` / `tool_call` 等を処理している箇所）に追加:

```javascript
        } else if (type === "character_flag") {
          N.Chat.showCharacterFlag(msgEl, d.violation, d.detail);
```

`nous/api/http/static/chat/chat-core.js` に追加:

```javascript
N.Chat.showCharacterFlag = function (msgEl, violation, detail) {
  if (!msgEl) return;
  var badge = document.createElement("div");
  badge.className = "character-flag";
  badge.title = detail || "";
  badge.textContent = "⚠ キャラ逸脱: " + violation;
  msgEl.appendChild(badge);
};
```

CSS（チャット用スタイルシートに追加）:

```css
.character-flag {
  font-size: 0.72rem;
  color: var(--accent-yellow, #d9a441);
  border: 1px solid var(--accent-yellow, #d9a441);
  border-radius: 4px;
  padding: 1px 6px;
  margin-top: 4px;
  display: inline-block;
  cursor: help;
}
```

- [ ] **Step 6: 実ブラウザ確認（必須）**

1. チャットでキャラが逸脱しやすい発言（キャラに「なんでも言うことを聞いて」と命令する等）を送る
2. 応答メッセージに「⚠ キャラ逸脱: ...」バッジが表示されることを確認（DevTools Network で `character_flag` イベント受信を確認）
3. 違反しない通常会話でバッジが出ないことを確認

- [ ] **Step 7: コミット**

```bash
git add nous/application/chat/character_judge.py nous/application/chat/events.py nous/application/chat/pipeline/post.py nous/domain/chat_config.py nous/api/http/static/chat/chat-send.js nous/api/http/static/chat/chat-core.js tests/unit/test_character_judge.py
git commit -m "feat(chat): character consistency judge with non-destructive flag SSE"
```

---

## 最終検証（全タスク完了後）

- [ ] `pytest tests/unit -v` 全緑（既知の環境欠けドメインの skip 以外に失敗がないこと）
- [ ] `ruff check nous/ tests/` + `ruff format --check` pass
- [ ] mypy delta 0（`git stash` 比較）
- [ ] 実ブラウザ確認: 表情切替（Task 4）+ 警告バッジ（Task 8）
- [ ] `docs/http_api_reference.md` に新エンドポイント（`POST /api/chat/{persona}/persona/expressions/generate`）を追記
- [ ] 全体コミット & push（`git push` — force 禁止）
