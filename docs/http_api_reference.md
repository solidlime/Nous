# Memory MCP — HTTP API Reference

All endpoints are served from the MCP HTTP server (default port **`26262`**).  
Persona is resolved from the `Authorization: Bearer <persona>` header, `X-Persona` header, or falls back to `"default"`.

---

## Authentication / 認証

| Priority | Method | Example |
|----------|--------|---------|
| 1 | Bearer token | `Authorization: Bearer herta` |
| 2 | X-Persona header | `X-Persona: herta` |
| 3 | Environment variable | `PERSONA=herta` or `MEMORY_MCP_DEFAULT_PERSONA=herta` |
| 4 | Default | `"default"` |

---

## MCP Transport

The FastMCP server exposes the standard MCP protocol at:

```
POST /mcp          # MCP Streamable HTTP transport (for MCP clients)
```

**Claude Desktop / MCP client config:**
```json
{
  "mcpServers": {
    "memory": {
      "url": "http://localhost:26262/mcp",
      "headers": {
        "Authorization": "Bearer <persona_name>"
      }
    }
  }
}
```

---

## Health & Personas

### `GET /health`
Health check with Qdrant connectivity status.

**Response:**
```json
{
  "status": "ok",
  "version": "3.0.0",
  "qdrant": "connected"
}
```

### `GET /api/personas`
List all available personas (scans data directory).

**Response:** `{ "personas": ["herta", "default", "alice"] }`

### `POST /api/personas`
Create a new persona with initialized databases.

**Request body:** `{ "persona": "alice" }`

### `DELETE /api/personas/{persona}`
Delete a persona and all its data. Cannot delete `"default"`.

### `PUT /api/personas/{persona}/profile`
Update persona profile fields.

**Request body:**
```json
{
  "user_info": { "name": "Alice", "preferred_address": "Alice-san" },
  "persona_info": { "nickname": "Al" },
  "relationship": "friend"
}
```

### `GET /api/stats/{persona}`
Get memory and vector statistics for a persona.

---

## Dashboard

### `GET /`
Serve the web dashboard UI (HTML).

### `GET /api/dashboard/{persona}`
Aggregated dashboard payload for a persona.

**Response fields:**
- `info` — persona context (name, relationship, emotion, equipment, etc.)
- `metrics` — total memories, content chars, vector count, tagged/linked counts
- `stats.timeline` — `[{date, count}]` array for the last N days (default 14)
- `knowledge_graph_url` — URL to the knowledge graph HTML, or `null`

---

## Memory Browsing

### `GET /api/observations/{persona}`
Paginated list of memories, sorted chronologically.

**Query params:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | 1 | Page number (1-based) |
| `per_page` | int | 20 | Items per page (max 100) |
| `sort` | str | `desc` | `desc` = newest first, `asc` = oldest first |
| `tag` | str | — | Filter by tag |
| `q` | str | — | Keyword search in content |

**Response:**
```json
{
  "success": true,
  "total": 142,
  "page": 1,
  "per_page": 20,
  "total_pages": 8,
  "items": [
    {
      "key": "memory_20250101_120000",
      "content_preview": "First 300 chars...",
      "emotion_type": "joy",
      "emotion_intensity": 0.8,
      "importance": 0.9,
      "tags": ["coding", "milestone"],
      "context_tags": ["promise"],
      "created_at": "2025-01-01T12:00:00",
      "updated_at": "2025-01-01T12:00:00",
      "privacy_level": "internal",
      "action_tag": "achievement",
      "environment": "home"
    }
  ]
}
```

### `GET /api/recent/{persona}`
Get the most recent memories for a persona.

**Query params:** `limit` (int, default 10)

**Response:** `{ "memories": [ { memory object... } ] }`

### `GET /api/search/{persona}`
Search memories for a persona.

**Query params:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `q` | str | `""` | Search text (required) |
| `limit` | int | 20 | Max results |
| `mode` | str | `hybrid` | Search mode: `semantic`, `keyword`, `hybrid`, `smart` |

---

## Memory CRUD

### `POST /api/memories/{persona}`
Create a new memory directly via HTTP.

**Request body:**
```json
{
  "content": "User prefers dark mode.",
  "importance": 0.7,
  "emotion_type": "neutral",
  "emotion_intensity": 0.0,
  "tags": ["preferences"],
  "privacy_level": "internal"
}
```

**Response:** `{ "success": true, "key": "memory_20250715_103000" }`

### `PUT /api/memories/{persona}/{key}`
Update an existing memory by key.

**Request body:** Same fields as POST (all optional).

### `DELETE /api/memories/{persona}/{key}`
Delete a memory by key.

**Response:** `{ "success": true }`

---

## Analytics（直叩き廃止 — dashboard集約 `/api/dashboard/{persona}` に一本化）

> `GET /api/emotions/{persona}`・`GET /api/strengths/{persona}` は削除済み。
> 感情・強度は dashboard の `context`・`strengths` 集約を参照すること。

---

## Knowledge Graph

### `GET /api/graph/{persona}`
Memory relationship graph for visualization (nodes + edges).

**Query params:** `limit` (int, default 200)

**Response:**
```json
{
  "nodes": [ { "id": "memory_...", "label": "preview...", "importance": 0.8 } ],
  "edges": [ { "source": "memory_a", "target": "memory_b", "weight": 1 } ]
}
```

---

## Import / Export（削除済み — d7）

> `POST /api/import/{persona}`・`GET /api/export/{persona}`・`POST /api/import-conversation/{persona}` は削除済み。

---

## Persona Dashboard Pages

### `GET /dashboard/{persona}`
Serve the persona chat dashboard UI (HTML).

---

## Chat Persona

### `POST /api/chat/{persona}/persona/expressions/generate`
Generate expression images for all supported emotions via ComfyUI, using the persona's
image generation config (`image_gen_*` fields in the persona chat config). Existing
images are skipped. Requires `image_gen_enabled: true`.

**Response:**
```json
{
  "generated": ["joy", "sadness"],
  "skipped": ["neutral"],
  "failed": []
}
```

- `generated` — emotions for which a new PNG was created
- `skipped` — emotions with an existing image or generation disabled
- `failed` — emotions whose generation errored

### `GET /api/chat/{persona}/persona/images/{file}`
Serve a persona image (self portraits and expression images such as `expr_joy.png`).

---

### SSE: `context.expression_changed`

Emitted on the dashboard SSE stream when the persona's expression changes.

```json
{ "emotion": "joy", "url": "/api/chat/herta/persona/images/expr_joy.png" }
```

The chat view swaps the persona avatar image to `url` on receipt.

---

## Core Memory Blocks

Blocks are named segments always injected into `get_context()` output — high-priority working memory for the AI agent.
No dedicated MCP tool — manage via HTTP API only.

### `GET /api/blocks/{persona}`
List all Core Memory Blocks for a persona.

**Response:**
```json
{
  "persona": "herta",
  "blocks": [
    {
      "name": "user_model",
      "content": "Pythonエンジニア。簡潔な説明を好む。FastAPIプロジェクト進行中。",
      "description": null,
      "updated_at": "2025-07-15T12:00:00"
    }
  ]
}
```

**Standard block names:**

| Name | Purpose |
|------|---------|
| `persona_state` | Persona's current internal state and ongoing goals |
| `user_model` | What the agent knows/infers about the user |
| `active_context` | Current session focus, open questions, ongoing topics |

Custom block names are also allowed.

### `POST /api/blocks/{persona}`
Write (create or overwrite) a Core Memory Block.

**Request body:**
```json
{
  "block_name": "user_model",
  "content": "Pythonエンジニア。簡潔な説明を好む。FastAPIプロジェクト進行中。"
}
```

Both `block_name` and `content` are required.

**Response:** `{ "ok": true }`

### `DELETE /api/blocks/{persona}/{block_name}`
Delete a Core Memory Block by name.

**Path params:** `block_name` — name of the block to delete (supports slashes via `:path`)

**Response:** `{ "ok": true }`

---

## Vector Store Admin（削除済み — d6）

> `POST /api/admin/rebuild/{persona}` は削除済み。

---

## Runtime Settings

### `GET /api/settings`
Get all runtime configuration values with metadata.

### `PUT /api/settings`
Update a runtime setting.

**Request body:** `{ "key": "log_level", "value": "DEBUG" }`

### `GET /api/settings/status`
Get reload status for runtime settings.

---

## Privacy Levels

Memories have a `privacy_level` field that controls dashboard visibility:

| Level | Value | Description |
|-------|-------|-------------|
| `public` | 0 | Visible to all |
| `internal` | 1 | Default — shown in dashboard |
| `private` | 2 | Hidden from dashboard |
| `secret` | 3 | Hidden from all read APIs |
