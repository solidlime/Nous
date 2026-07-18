# HANDOFF — 2026-07-18

## セッション概要

portrait 機能をコードベースから完全削除。backend（Python）・frontend（JS/CSS/HTML）・tests・docs を全掃除。

## 完了したコミット

```
bb0eeb8 chore: remove dead portrait constants and overview section
fab6169 docs: remove portrait references from CLAUDE.md and llm_usage_guide.md
35e0974 chore: remove portrait frontend references and fix tests
7d94c07 chore: remove remaining portrait references from Python backend
2cabf8a feat: remove portrait feature from Python backend
```

## 実装サマリ

### 完全削除したファイル（11件）
- `nous/application/portrait/__init__.py`, `service.py`
- `nous/api/mcp/_tools_portrait_scene.py`
- `nous/api/http/routers/portrait.py`
- `nous/api/http/static/chat/chat-portrait.js`
- `nous/api/http/static/portrait.js`, `portrait.css`
- `nous/domain/persona/portrait_prompt.py`
- テスト 3ファイル（portrait関連テスト）

### 部分削除したファイル（20件+）
- Python: settings.py, runtime_config.py, event_bus.py, use_cases.py, chat_config.py, connection.py, routes.py, tools.py, definitions.py, builtin.py, comfyui.py, routers/chat.py, routers/__init__.py
- HTML/Sections: base.py, overview.py, chat.py
- JS: chat-settings.js, settings.js, chat-core.js, constants.js, overview.js, sse.js
- CSS: chat.css
- Docs: CLAUDE.md, docs/llm_usage_guide.md

### 変更行数
- 5 commits, 約600行削除（11ファイル削除 + 25ファイル修正）
- 最終テスト: 1535 passed, 1 deselected（pre-existing）

### 注意点
- `image_gen_comfyui_url` は `image_generate` ツール用に ChatConfig に残した
- フロントエンドの portrait 領域は削除（絵文字プレースホルダは元から none）
- 唯一の pre-existing failure: `test_should_summarize_false_when_not_configured`（compress step, unrelated）

## 残タスク
- なし。portrait 削除は完全完了。
