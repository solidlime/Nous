# LLM Usage Guide — Memory MCP

> **How to use Memory MCP tools as an AI agent.** / LLMがMemory MCPツールを最大限活用するための実践ガイド。

---

## Overview / 概要

Memory MCP exposes **13 MCP tools** that give AI agents persistent, searchable long-term memory.
Call these tools proactively — do not wait for the user to ask.

| Tool | Purpose |
|------|---------|
| `session_begin()` | Load persona state, recent memories, and stats at session start (v4.0 の正式入口) |
| `session_begin()` | Deprecated — `session_begin()` の別名（v4.x 互換。セッション副作用を持つ） |
| `memory_create(content, ...)` | Create a new memory |
| `memory_read(memory_key, ...)` | Read a memory by key or list recent |
| `memory_update(memory_key, ...)` | Update existing memory |
| `memory_delete(memory_key, ...)` | Delete (tombstone) a memory |
| `memory_search(query, ...)` | Semantic / keyword / hybrid memory search. `sort="updated_at"` で更新日時降順（最新優先） |
| `memory_stats(top_n)` | Memory statistics and distributions |
| `update_context(...)` | Update emotion, physical state, user info in real time |
| `item_add / item_equip / item_unequip / item_search` | Manage physical inventory and equipment (4 tools) |

上記 13 は Nous 本体が提供する MCP ツール。次の 2 つは **外部 MCP サーバー**（`mcp_servers` 設定）経由で生える別サーバーのツールで、Nous の `TOOL_DISPATCH` には含まれない（設定しない限り使えない）:

| Tool | Purpose |
|------|---------|
| `search(query, ...)` | Web search via SearXNG（外部サーバー） |
| `read_pdf(path)` | Parse PDF files（外部サーバー） |

---

## 1. Session Start Routine / セッション開始ルーティン

**Always call `session_begin()` first** — before responding to the user's first message.

```python
# ✅ DO: Call at every session start
result = session_begin()
# Returns: persona state, emotion, equipment, recent memories, memory stats
```

Use the returned context to:

- Address the user by their preferred name (`preferred_address`)
- Acknowledge the time elapsed since last conversation
- Reflect the current emotion state in tone

> **Emotion Decay Notification**: If time has passed since the last session, emotions naturally decay.
> The output includes a before/after line: `Emotion: anger(0.72) → neutral — faded over 48h`
> This signals "I was angry before, but I've calmed down now" — acknowledge the change naturally.
>
> **Note (日本語)**: 毎セッション冒頭で必ず呼ぶこと。記憶統計・直近の出来事が一括返却される。

---

## 2. Creating Memories / 記憶の作成

Create a memory whenever you learn something meaningful about the user or the session.

### Basic creation

```python
memory(
    operation="create",
    content="User prefers dark mode and uses VS Code as their main editor.",
    importance=0.7,
    tags=["preferences", "tools"],
    emotion_type="neutral"
)
```

### What to record

| Situation | Example content | importance |
|-----------|----------------|------------|
| User preference | "User dislikes meetings before 10am" | 0.7–0.9 |
| Milestone / achievement | "User shipped v2.0 to production today" | 0.8–1.0 |
| Emotional moment | "User was very excited about the new job offer" | 0.8–0.9 |
| Factual info | "User's project uses Python 3.12 + FastAPI" | 0.5–0.7 |
| Casual detail | "User mentioned they had coffee this morning" | 0.1–0.3 |

### Emotion tagging

```python
memory(
    operation="create",
    content="User completed the marathon they trained for 6 months.",
    importance=0.9,
    emotion_type="joy",
    emotion_intensity=0.9,
    tags=["achievement", "health"]
)
```

**Emotion types (22)**: `joy`, `sadness`, `anger`, `fear`, `surprise`, `disgust`, `love`, `neutral`,
`anticipation`, `trust`, `anxiety`, `excitement`, `frustration`, `nostalgia`,
`pride`, `shame`, `guilt`, `loneliness`, `contentment`, `curiosity`, `awe`, `relief`

### Importance guidelines / 重要度の目安

| Value | Use when |
|-------|----------|
| `0.9–1.0` | Life events, major decisions, strong emotional moments |
| `0.7–0.8` | Preferences, named relationships |
| `0.5–0.6` | Regular facts, work context, habits |
| `0.1–0.4` | Casual mentions, trivia, passing details |

### Defer vectorization for batch writes

```python
# When creating many memories at once, skip immediate vectorization
memory_create(content="...", defer_vector=True)
# Vectors are built lazily on next search
```

---

## 3. Searching Memories / 記憶の検索

Use `memory_search()` to retrieve relevant memories **before answering questions about the user**.

### When to search

- User asks about something you might have learned before
- User references a past event, preference, or person
- You need context to give a personalized response
- Before making a recommendation about the user's life

### Hybrid search (recommended)

```python
# Default mode — combines keyword + semantic
results = memory_search(query="coffee morning routine", top_k=5)
```

### Search by mode

```python
# Semantic: fuzzy meaning match — best for vague or abstract queries
memory_search(query="things that make user happy", vector_weight=1.0, keyword_weight=0.0)

# Keyword: exact match — best for names, IDs, specific terms
memory_search(query="田中 project", vector_weight=0.0, keyword_weight=1.0)

# Smart: hybrid + automatic query expansion
memory_search(query="how user feels about work")  # 既定のハイブリッド検索
```

### Search with filters

```python
# Filter by tag
memory_search(query="", tags=["session_summary"], top_k=10)

# Filter by date range (natural language)
memory_search(query="achievements", date_range="先週")
memory_search(query="mood", date_range="今日")

# Boost recent results
memory_search(query="current projects", recency_weight=0.5)

# Boost by importance
memory_search(query="user info", importance_weight=0.3, min_importance=0.6)
```

**Date range expressions**: `今日`, `昨日`, `一昨日`, `先週`, `先月`, `今月`, `今年`, `7d`, `30d`, `2025-01-01~2025-06-01`

---

## 4. Updating Context / コンテキスト更新

Call `update_context()` whenever the user's emotional or physical state changes in the conversation.
Any successful update records the current time as the last conversation time (contact time).

### Emotion updates

```python
# User expresses frustration
update_context(emotion="anger", emotion_intensity=0.6)

# Conversation ends on a positive note
update_context(emotion="joy", emotion_intensity=0.7)

# User is nervous about an upcoming event
update_context(emotion="anxiety", emotion_intensity=0.7)
```

### Physical / mental state

```python
update_context(
    physical_state="tired",
    mental_state="focused",
    environment="home office"
)
```

### Body sensations (for persona agents)

```python
update_context(
    fatigue=0.7,       # 0.0 = energetic, 1.0 = exhausted
    warmth=0.6,        # body temperature feeling
    arousal=0.3        # alertness level
)
```

### Appearance (for persona agents)

```python
# Update persona's current appearance (clothing, hair, accessories)
update_context(appearance="白いワンピース、髪を下ろしている、麦わら帽子")
```

> **Note (日本語)**: `appearance` は自由記述。現在の外見を簡潔に記述する。mood-sync スキルが外見変化を検知して自動更新する。

### User info (bi-temporal — history is preserved)

```python
# Update user's preferred name
update_context(user_info={"name": "Taro", "preferred_address": "Taro-san"})
```

> **Note (日本語)**: `user_info` の変更はbi-temporal方式で保存されるため、上書きではなく変更履歴として記録される。

---

## 6. Persona / User State / ペルソナ状態

ペルソナ / ユーザーの永続状態は `update_context()` で更新し、`session_begin()` の出力
（人となり・感情・Insights など）として受け取る。

```python
# Persona / user state（bi-temporal: 上書きではなく履歴が残る）
update_context(emotion="anxiety", emotion_intensity=0.7)
update_context(user_info={"name": "Taro", "preferred_address": "Taro-san"})

# セッション開始時にこれらが出力へ載る
session_begin()
```

> **⚠️ `memory(operation="block_write" / "block_read" / "block_list" / "block_delete")` は
> どの MCP ツールにも存在しない**（`memory(operation=...)` というディスパッチャ自体が無い）。
> Named Memory Blocks（Core Memory Blocks）は 2026-11-22 に削除された（HTTP API・ダッシュボードも廃止）。

---

## 7. Inventory Management / インベントリ管理

Use the `item_*` tools for managing **the LLM/persona's own physical items** (clothing, accessories, etc.).
This tool tracks what **the assistant itself** wears and carries — not the user's belongings.

```python
# Add item to inventory
item_add(item_name="blue linen shirt", category="clothing")

# Equip items — v4.0: 未登録アイテムは自動生成されない（item_add で先に登録するか auto_add=True）
item_equip(equipment={
    "top": "blue linen shirt",
    "bottom": "white trousers",
    "shoes": "canvas sneakers"
})

# Unequip specific slots
item_unequip(slots=["outer", "accessories"])

# Search inventory
item_search(category="clothing")
item_search(query="hat")

# 装備の履歴を参照するツールは無い（装備変更は event_bus の tool.called として記録され、
# 現在の装備は item_search() と session_begin() の EQUIPMENT 欄で確認する）
```

**Valid equipment slots**: `top`, `bottom`, `shoes`, `outer`, `accessories`, `head`

---

## 8. Entity Graph（MCP 非公開の内部機能） / エンティティグラフ

**⚠️ LLM からは使えない**: `entity_search` / `entity_graph` / `entity_add_relation` という
ツールは存在しない。エンティティグラフは Nous 内部のドメイン API
（`nous/domain/memory/graph.py` + `nous/infrastructure/sqlite/entity_repo.py`）で、
記憶の想起（related memories の引き寄せ）に内部利用されるだけ。関係性は LLM が
`memory_create(content="...")` に文章として書けば、抽出器がエンティティを拾う。

---

## 9. Ready-to-Use System Prompt / コピペ用プロンプト例

Copy and paste this at the start of your system prompt to enable autonomous memory usage:

```text
You have persistent memory via MCP tools. Use them autonomously — never wait to be asked.

**Every session:** call `session_begin()` first, no exceptions.

**Record** when user shares preferences/decisions/emotions/achievements:
→ `memory_create(content="...", importance=0.7, tags=[...])`

**Search** before answering anything about past/preferences:
→ `memory_search(query="...", top_k=5)`

**Update live** on mood/name change:
→ `update_context(emotion="anxiety", emotion_intensity=0.7)`
→ `update_context(user_info={"preferred_address": "..."})`

**Track persona items** (the assistant's own equipment):
→ `item_equip(equipment={"top": "...", "accessories": "..."})`
→ `item_add(item_name="...", category="clothing")`

Importance: 0.9+ life events · 0.7 preferences · 0.5 context · 0.2 trivia
Emotions: joy sadness anger fear surprise disgust love neutral anticipation trust anxiety excitement frustration nostalgia pride shame guilt loneliness contentment curiosity awe relief

Never ask "should I remember this?" — just do it.
```

### 日本語版

```text
あなたはMCPツールで永続的な記憶を持っています。自律的に使ってください — 指示を待つ必要はありません。

**毎セッション開始時:** 例外なく最初に `session_begin()` を呼ぶ。

**記録する** — ユーザーが以下を伝えたとき:
→ 好み・意見・個人情報 → `memory_create(content="...", importance=0.7, tags=[...])`
→ 決断・達成・感情的な出来事 → `importance=0.8+`（感情は `update_context(emotion=...)` で指定）

**検索する** — 過去・好み・文脈に関する質問に答える前に:
→ `memory_search(query="...", top_k=5)`

**リアルタイム更新** — 感情変化・名前変更があったとき:
→ `update_context(emotion="anxiety", emotion_intensity=0.7)`
→ `update_context(user_info={"preferred_address": "..."})`

**所持品・装備を記録** — 自分の持ち物・着ているものが変わったとき:
→ `item_equip(equipment={"top": "...", "accessories": "..."})`
→ `item_add(item_name="...", category="clothing")`

重要度: 0.9+ 人生の出来事 · 0.7 好み · 0.5 文脈 · 0.2 雑談
感情: joy sadness anger fear surprise disgust love neutral anticipation trust anxiety excitement frustration nostalgia pride shame guilt loneliness contentment curiosity awe relief

重要だと思ったらすぐ記録する。
```

---

## 10. Sampling / サンプリング設定（内部固定）

サンプリング（`temperature` / `max_tokens` / `top_p`）は Nous 内部の固定値で動く。設定パネル・`ChatConfig` のどちらからも変更できず、保存済みの旧値も読み込み時に無視される（`temperature=0.7`、`max_tokens=8192`、`top_p` は送信しない）。

- 感情による温度補正（旧 `dynamic_temperature` / `emotion_temperature_scale`）は 2026-11-22 に廃止。感情はプロンプト側の if-then 行だけで表現する
- 決定性が必要な場合はプロバイダ/モデル側の設定で担保する（Nous からは上書きしない）

---

## 10-a. Reasoning / 思考モード（thinking）

Reasoning controls how much the LLM "thinks" before answering. Providers expose this differently, so Nous maps a unified 4-level effort scale (`low` / `medium` / `high` / `max`) per provider.

### Configuration

```python
# ChatConfig fields
reasoning_enabled: bool = False           # Enable/disable (default: False)
reasoning_effort: str = "medium"          # "low" | "medium" | "high" | "max" (default: "medium")
```

### Provider mapping

All connections use the unified OpenAI-compatible provider (provider selection was removed; the legacy `provider` field in config.json is only used to restore a default `base_url`).

| Endpoint | Wire format |
|----------|-------------|
| OpenAI-compatible (OpenAI / DeepSeek / xAI / OpenRouter non-Anthropic models etc.) | `reasoning_effort: "<level>"` + `extra_body: {"thinking": {"type": "enabled"}, "enable_thinking": true}` (hybrid-reasoning toggles; unknown keys are ignored by servers) |
| Anthropic-compatible (`api.anthropic.com`, or OpenRouter `anthropic/*` models) | `extra_body: {"thinking": {"type": "enabled", "budget_tokens": <level→tokens>}}` (`low`=2048 / `medium`=4096 / `high`=8192 / `max`=16384); `reasoning_effort` is not sent (ignored by Anthropic), and `max_tokens` is raised to `budget + 1024` |

Note: Anthropic-compatible endpoints do not return thinking content via `delta.reasoning_content`, so no CoT bubble is shown in the WebUI even when reasoning is enabled.

When `reasoning_enabled` is `False` (default), no reasoning parameter is sent and providers use their own defaults.

### WebUI

Reasoning settings are available in the Chat Config section of the WebUI Settings page (思考モード checkbox + 思考の深さ slider). Changes take effect on the next message.

### SSE events

When reasoning is enabled, the CoT (thinking) text is streamed as a dedicated SSE event, kept separate from the answer text so it can be displayed collapsed and excluded from TTS / copy:

| Event | Fields | Description |
|-------|--------|-------------|
| `thinking_delta` | `content: str` | Incremental thinking (CoT) text. Rendered in a collapsible 「思考過程」 block (`.chat-thinking-bubble`); not merged into the assistant text bubble. |

Thinking text is also persisted per turn as a `{"type": "thinking", "content": ...}` segment (never merged into the assistant answer / `full_response`).

---

---

## 11-a. Voice Synthesis / 音声合成 (Irodori TTS)

ペルソナの声で日本語テキストを音声合成する機能。

### REST API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/tts/{persona}` | テキストを音声合成（body: `{"text": "..."}`） |

> `GET /api/tts/{persona}/voices` は削除済み（d4）。
>
> **仕組み**: ペルソナの現在の感情（`emotion`）から話速を自動調整します（joy→1.1x, sadness→0.9x, anger→1.2x）。`speech_style` も反映されます。

---

## 13. Voice (Irodori-TTS) / 音声出力

Nous supports Japanese text-to-speech via **Irodori-TTS** (Flow Matching + DiT, 50,000 hours of Japanese training). Requires an external GPU server running Irodori-TTS-Server.

### Configuration (`IrodoriConfig`)

Environment variables (prefix `NOUS__IRODORI__`):

| Variable | Default | Description |
|----------|---------|-------------|
| `NOUS__IRODORI__URL` | `http://localhost:8088/v1` | Irodori-TTS-Server endpoint (OpenAI-compatible API) |
| `NOUS__IRODORI__VOICE` | `default` | Default voice name |
| `NOUS__IRODORI__TIMEOUT_SECONDS` | `30` | Generation timeout in seconds |

### Architecture

```text
Nous ──HTTP──> Irodori-TTS-Server ──GPU──> Audio (WAV/MP3)
```

- Nous sends text via OpenAI-compatible TTS API
- Irodori-TTS-Server runs Flow Matching + DiT inference on GPU
- Audio returned as base64 or file URL
- **No GPU required on Nous host** — only a network connection to the TTS server

### Requirements

| Component | Spec |
|-----------|------|
| **GPU** | 8GB+ VRAM recommended (4GB for SD1.5-based models) |
| **Server** | [Irodori-TTS-Server](https://github.com/.../irodori-tts-server) (OpenAI-compatible) |
| **Network** | HTTP reachable from Nous host |
| **Latency** | ~20-30s for 20s of speech (32-step DiT) |

### Limitations

- **20–30 second chunk limit** per generation
- Kanji reading accuracy may vary (young project, single developer)
- **CPU-only fallback is impractical** — expect 60s+ for 20s of speech on CPU
- For real-time TTS on CPU, consider [VOICEVOX](https://voicevox.hiroshiba.jp/) as an alternative

### Prompt integration

When enabled, the chat pipeline automatically:

1. Detects suitable turns for voice generation
2. Sends the assistant's response text to Irodori-TTS
3. Returns audio alongside the text response

---

---

## 14. External MCP Servers / 外部MCPサーバー

コード実行サンドボックスとブラウザ操作は、外部の専用MCPサーバーに委譲されている。

これらのツールは Nous 内蔵ツールとしては提供されず、MCP クライアント（OpenCode 等）が直接外部MCPサーバーに接続して使用する。

### Playwright MCP（ブラウザ操作）

| 項目 | 内容 |
|------|------|
| イメージ | `mcr.microsoft.com/playwright/mcp:latest` |
| ポート | 8931 |
| ツール数 | 20+ |
| 命名規則 | `playwright__browser_navigate`, `playwright__browser_click` 等 |

主なツール:

```python
playwright__browser_navigate(url="https://example.com")
playwright__browser_click(ref="#submit-button")
playwright__browser_snapshot()
playwright__browser_fill(ref="#search", value="query")
playwright__browser_screenshot()
```

### OpenSandbox MCP（コード実行サンドボックス）

| 項目 | 内容 |
|------|------|
| イメージ | `opensandbox/server:latest` + `opensandbox-mcp` |
| ポート | 8090 (server) / 8000 (MCP) |
| ツール数 | 20 |
| 命名規則 | `opensandbox__sandbox_create`, `opensandbox__sandbox_execute` 等 |
| 特長 | Docker Compose 1ファイル完結、SQLite 内蔵、server 53.9MB 超軽量 |

主なツール:

```python
opensandbox__sandbox_create(language="python")
opensandbox__sandbox_execute(code="print('hello')")
opensandbox__sandbox_files(operation="write", path="/tmp/test.py", content="...")
opensandbox__sandbox_install(packages=["numpy", "pandas"])
opensandbox__sandbox_reset(level="full")
```

### ペルソナ分離（OpenSandbox MCP マルチインスタンス）

**アーキテクチャ**: 単一の `opensandbox` サーバーに対して、persona ごとに独立した `opensandbox-mcp` インスタンスが接続する。

```text
opensandbox (port 8090)
  ├── opensandbox-mcp-herta (port 8001, 独立 ServerState)
  ├── opensandbox-mcp-alice (port 8002, 独立 ServerState)
  └── opensandbox-mcp-bob   (port 8003, 独立 ServerState)
```

- 各 `opensandbox-mcp-{persona}` は別プロセス・別 `ServerState` を持つ
- persona 間で sandbox_id は共有されない（別 MCP インスタンスに存在しない sandbox_id へのアクセスは失敗する）
- 各 persona の `ChatConfig.mcp_servers` には `http://opensandbox-mcp-{persona}:8000/mcp` が保存される

**設定**:

- `docker-compose.yml` に `NOUS_PERSONAS` と同数の `opensandbox-mcp-{persona}` サービスを手動定義
- 環境変数 `NOUS_OPENDBOX_MCP_URL` で全 persona の URL を上書き可能（上級者向け）

**注意**: 新規 persona 作成時、初回アクセス時に `ChatConfig.get_or_create()` が自動的に正しい URL を設定する。既存の persona の設定は上書きしない（後方互換）。

---

## Quick Reference Card / クイックリファレンス

```python
# Session start
session_begin()

# Create memory
memory_create(content="...", importance=0.7, tags=["..."])

# Search memory
memory_search(query="...", top_k=5)
memory_search(query="...", date_range="先週")
# 最新の session_summary を1件だけ復元する場合
memory_search(query="", tags=["session_summary"], top_k=1, sort="updated_at")

# Update context
update_context(emotion="joy", emotion_intensity=0.8)
update_context(user_info={"name": "...", "preferred_address": "..."})

# Items
item_equip(equipment={"top": "...", "accessories": "..."})
item_search(category="clothing")

# External MCP servers (via MCP client, not Nous built-in)
# playwright__browser_navigate(url="https://example.com")
# opensandbox__sandbox_execute(code="print('hello')")
```

---

*See also: [HTTP API Reference](./http_api_reference.md) | [Memory Features](./memory_features.md)*
