# Memory MCP — HTTP API Reference

All endpoints are served from the MCP HTTP server (default port **`26262`**).
Persona is resolved from the path parameter, the `Authorization: Bearer <persona>` header, the `X-Persona` header, or falls back to `"default"` (priority: path > Bearer > X-Persona > default > env).
When `NOUS_API_KEY` is set, the Bearer token must equal the key (401 otherwise) and the persona comes from the path param / `X-Persona` header only.

---

## Authentication / 認証

| Priority | Method | Example |
|----------|--------|---------|
| 0 | Path parameter | `/api/memories/herta` |
| 1 | Bearer token | `Authorization: Bearer herta` |
| 2 | X-Persona header | `X-Persona: herta` |
| 3 | Environment variable | `PERSONA=herta` or `MEMORY_MCP_DEFAULT_PERSONA=herta` |
| 4 | Default | `"default"` |

---

## MCP Transport

The FastMCP server exposes the standard MCP protocol at:

```text
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
  "version": "4.0.0",
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

この一括版は互換のために残してある。v4 の UI は下の v2 分割版だけを叩く。

### `GET /api/v2/overview/{persona}`

Overview タブの初回描画用。KPI・state memories・wiki 要約だけを返す
（recent / items / 画像は含まない）。

`stats` / `context` は v1 の `stats` / `info` と同じ形。`wiki` は
`{pages, projects, reading[]}` で `reading` は更新順の先頭5件。

### `GET /api/v2/recent/{persona}`

直近の記憶。`?limit=`（既定10・最大50）、`?full=1` で本文を200字切りしない完全版を返す。

### `GET /api/v2/equipment/{persona}` / `items`

一括版からセクション単位で切り出したもの。レスポンスは `{"persona": ..., "<セクション名>": [...]}` で、
キー以外の形は v1 と同一。存在しない persona は v1 と同じ 404。
2本とも同じ形なので以下にまとめて挙げる。

### `GET /api/v2/equipment/{persona}`

### `GET /api/v2/items/{persona}`

### `GET /api/v2/images/{persona}`

`images` は形が違う: `{persona, latest_self_portrait, generated_images[]}`。
`generated_images` は最大20件で、`url` は
`/api/chat/{persona}/persona/images/{filename}`。

---

## Memory Browsing

### `GET /api/observations/{persona}`

Paginated list of memories, sorted chronologically.

**Query params:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | 1 | Page number (1-based, max 10000) |
| `per_page` | int | 20 | Items per page (max 1000) |
| `sort` | str | `desc` | `desc` = newest first, `asc` = oldest first |
| `tag` | str | — | Filter by tag |
| `q` | str | — | Keyword search in content |
| `mode` | str | — | `recent` の時は `per_page` 件を新しい順で返す別モード（`memories` のみ） |

**Response:**

```json
{
  "persona": "herta",
  "page": 1,
  "per_page": 20,
  "total_count": 142,
  "total_pages": 8,
  "memories": [
    {
      "key": "memory_20250101_120000",
      "content": "Full memory body...",
      "emotion": "joy",
      "emotion_intensity": 0.8,
      "importance": 0.9,
      "tags": ["coding", "milestone"],
      "privacy_level": "internal",
      "environment": "home",
      "created_at": "2025-01-01T12:00:00",
      "updated_at": "2025-01-01T12:00:00"
    }
  ]
}
```

`memories[]` は Memory レコード全体（`content` はプレビューではなく本文）。

### `GET /api/search/{persona}`

Search memories for a persona.

**Query params:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `q` | str | `""` | Search text |
| `limit` | int | 20 | Max results |
| `mode` | str | `hybrid` | Search mode: `semantic`, `keyword`, `hybrid`, `smart` |
| `project` | str | なし | プロジェクト slug（canonical 規約 `[a-z0-9][a-z0-9-]*`、大文字・`_` は正規化）。指定時は `project:<slug>` タグの記憶と同 project の wiki ページを優先する。不正値は無視（`project: null` になる） |
| `date_range` | str | なし | 期間フィルタ |
| `min_importance` | float | なし | 重要度の下限 |
| `emotion` | str | なし | 感情で絞る |
| `decision` | str | なし | `1`/`true`/`on`/`yes` で decision gate を有効化 |
| `hops` | int | なし | multi-hop 数（上限あり） |
| `coverage` | float | なし | 被覆率重みの上書き |
| `request_id` | str | なし | 監査相関 ID |

**Response:**

```json
{
  "persona": "herta",
  "query": "...",
  "limit": 3,
  "project": "nous",
  "results": [
    { "memory": { "key": "memory_...", "content": "...", "tags": ["project:nous"] },
      "score": 1.125, "source": "hybrid", "time_weight": 0.5 }
  ],
  "wiki": [
    { "slug": "project-nous-arch", "title": "...", "project": "nous",
      "excerpt": "...", "score": 1.0 }
  ],
  "nodes": [], "edges": [],
  "injection": "[NOUS CONTEXT]\n[最近のできごと — 他クライアントとの活動を含む]\n- ...\n\n<retrieved_data>\n...\n</retrieved_data>\n自動注入は軽い文脈補助。...",
  "state": {
    "emotion": "neutral", "emotion_intensity": 0.0,
    "physical_state": null, "mental_state": null,
    "environment": "自宅", "relationship_status": "「知人」以上「友人」未満。",
    "body": { "fatigue": 0.086, "warmth": 0.5, "arousal": 0.0, "heart_rate": 0.5 },
    "user": { "name": "らうらう", "nickname": "らうらう" }
  }
}
```

- `project` は正規化後の slug（未指定・不正値は `null`）。
- `state` は現在の状態（感情・体調・環境・関係性・ユーザー情報）の読み取り専用ビュー（構造化・後方互換）。取得失敗時は `null`。
- `injection` は **そのままプロンプトに載せる文字列**（チャットの `[NOUS CONTEXT]` 揮発ブロックと同一整形。
  整形は `nous/application/chat/pipeline/injection.py` が唯一の定義）。digest → time_context → emotion →
  `<retrieved_data>`（`<current_state>` / `<related_memories>` / `<related_wiki>`）→ 読み上げ抑制の 1 文。
  空セクションは省略し、全空なら `""`。整形失敗時も `""`（`results[]` / `wiki[]` は無傷）。
  persona ChatConfig の `memory_min_score` は `injection` の記憶行にだけ効き、`results[]` は無フィルタ。
- `injection` は state の減衰を適用しない（GET で書き込み副作用を起こさない）。チャット経路との明示的な差。
- `time_weight` は decision gate の時間減衰（未使用時は `null`）。
- `project` 指定時は **候補プールを広げてから** ブーストし、最後に `limit` で切る（`limit*3`、engine 側の pool 上限は 60）。
  `limit < 20` で decision gate が有効なときは gate の採否も変わり得る（順位だけの変更ではない）。
- `wiki[]` も同じ `project` でブーストされる（加算 0.3、切り詰め前）。`score` は従来どおり 0-1。
- `wiki[]` はページファイルを読むので、`WikiConfig.enabled=false` でも既存ページは返る。

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
  "privacy_level": "internal",
  "source_context": null,
  "defer_vector": false
}
```

`emotion_type` は `emotion` のエイリアス（どちらでも可）。body が JSON object でない（list/str 等）場合は 422。

**Response (201):** `{ "status": "ok", "memory": { ...Memory レコード... }, "cache_invalidated": true }`

### `PUT /api/memories/{persona}/{key}`

Update an existing memory by key.

**Request body:** Same fields as POST (all optional; 空ボディは 400。object でない body は 422）。

**Response:** `{ "status": "ok", "memory": { ...Memory レコード... } }`

### `DELETE /api/memories/{persona}/{key}`

Delete a memory by key.

**Response:** `{ "status": "ok", "deleted": "memory_20250715_103000" }`

---

## Analytics（直叩き廃止 — dashboard集約 `/api/dashboard/{persona}` に一本化）

> `GET /api/emotions/{persona}`・`GET /api/strengths/{persona}` は削除済み。
> 感情・強度は dashboard の `context`・`strengths` 集約を参照すること。

---

## Knowledge Graph

### `GET /api/graph/{persona}`

Memory relationship graph for visualization (nodes + edges).

**Query params:** `limit` (int, default 200, 1〜1000。範囲外・非整数は 400)

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

## Project Context (kanban #8)

### `GET /api/project/{persona}/{slug}/context`

`project:<slug>` 単位の集約ビュー。サーバ側で既存の規約を読むだけで、新しい集計テーブルは持たない:

| Section | Source |
|---|---|
| `decisions` | 記憶の `decision` type タグ（タグ欠けは本文分類にフォールバック） |
| `open_questions` | 記憶の `open-question` タグ（`nous/application/wiki/questions.py`） |
| `wiki` | `WikiStore` ページの `project` が slug と一致するもの |
| `timeline` | slug の `project:` タグ付き記憶（新しい順） |

各セクション最大 30 件。本文は 400 字で切る。ダッシュボードの **Projects** タブがこれを描画する。

---

### `GET /api/metrics/{persona}`

観測値を返す（kanban #10）。

- `search`: `count` / `zero_result` / `zero_result_rate` / `p50_ms` / `p95_ms` — **プロセス内**（再起動で 0 に戻る、直近 500 サンプル）
- `tools`: MCP ツール名別の呼び出し回数（同上）
- `wiki` / `events`: `session_events` の集計（恒久記録側）

Activity タブの上部に 1 行で出る。

---

## Wiki（編纂知識の手動保守・kanban #2/#7）

ファイル層（`data/wiki/<persona>/`）が正本。索引（Qdrant）はミラーで、更新失敗は保存を止めない。

### `GET /api/wiki/{persona}`

ページ一覧。`?q=` で slug / title / 本文の部分一致に絞る（本文一致は `body_hits` 件数付き）。

### `GET /api/wiki/{persona}/{slug}`

本文（markdown 生）。`?q=` を渡すと一致行（`matches`）と逆リンク（`backlinks`）を返す。

### `PUT /api/wiki/{persona}/{slug}`

ダッシュボードからの保存。既存ページなら `sources` / `project` / `tags` を引き継ぐ。

### `DELETE /api/wiki/{persona}/{slug}`

削除（索引落としは best-effort）。削除前の本文は履歴に残る。

### `GET /api/wiki/{persona}/_history/{slug}`

改訂履歴（新しい順・本文なし）。

### `GET /api/wiki/{persona}/_history/{rev}/{slug}`

過去の版 1 つ（本文込み、`current_body` 付き）。

### `POST /api/wiki/{persona}/_restore/{rev}/{slug}`

過去の版を書き戻す。書き戻し自体も 1 リビジョンとして残る（追記型）。

### `POST /api/wiki/{persona}/_recompile`

手動再編纂（202）。ダッシュボードからはプラグイン鍵なしで呼べる代わりに persona 単位 60 秒の
クールダウンがある。外部からの `POST /api/wiki/run/{persona}` は plugin API key 必須。

---

---

## Chat Persona

### `GET /api/chat/{persona}/layout`

Chat タブの内側（記憶パネル・本体・サイドバー）だけを返す。v4 は shell を
SSR し、chat.chunk.js がこの HTML を空の `#chat-layout` へ注入してから chat の
各 script を読む（script が自分の DOM を見つけられる順序を守るため、wrapper も
asset タグも含めない）。存在しない persona は 404。

### `POST /api/chat/{persona}/approval`

エージェントが承認待ちで停止しているツール呼び出しに答える（`/api/chat/{persona}` のストリーム中に `approval_required` が届く）。

- body: `{"approval_id": str, "decision": "allow" | "deny"}`
- 200 `{"resolved": true}` — 該当の承認待ちが見つかり、決定を適用した
- 404 `{"resolved": false}` — 該当なし（タイムアウト後に届いた返答など）

---

### `GET /api/chat/{persona}/events/epoch`

サーバー再起動検出用の轻量 probe（2026-11-22 追加）。クライアントは SSE
再接続直後に呼び、応答の epoch が手元の基線と異なれば「再起動で ring の
seq が 1 に巻き戻った」と判定して追跡中 turn の回復処理に入る。

- 200 `{"epoch": "<12 hex>"}` — TurnHub のプロセス単位一意値
- 404 — persona 不在

`GET /api/chat/{persona}/events` の SSE `id:` は `"<epoch>:<seq>"` 形式で
送出される（旧クライアント互換のため生 int の受け入れも維持）。
`?last_seq=` は `<epoch>:<seq>` を受付け、epoch が不一致なら 0 扱いと
なり ring 全量が再生される（クライアント側の skip 規則で冪等）。

---

### `GET /api/chat/{persona}/commitments`

チャット画面の内省（Insights）パネルの供給源。`reflection` タグ付き記憶を更新順で
最大5件返す。旧 `goals` キー（アクティブな目標）は 2026-11-22 の Goals 削除で
廃止され、応答は `insights` 専用。

- 200 `{"insights": [{"content": "...", "key": "...", "created_at": "2026-11-01T12:00:00"}]}`
- 404 `{"error": "Persona not found"}` — persona 不在

---

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

## Session Begin

### `POST /api/session/{persona}/begin`

1ターン開始時のコンテキスト取得を HTTP から行う（MCP `session_begin` と同一の実装）。
`get_context()` が持っていた副作用（会話時刻の記録・ワンショット状態の消費）はこの経路に寄せてある。

**Response（既定は envelope）:**

```json
{ "ok": true, "data": { "context": "...", "notes": ["..."] }, "error": null }
```

`notes` はターン前に本人へ渡したい一言。今は1種類——長い沈黙を埋めるメモ（#37、`silence_hours` 以上間が空いたときだけ）。無ければ空配列。生成に失敗しても `notes` には `warning: ...` が1行入るだけで、begin 自体は成功する。

`?compat=legacy` を付けると v4.0 以前のフラット形式（`{ok, result}`）を返し、
`compat=legacy used: POST /api/session/{persona}/begin` を WARNING で1行出す。
`legacy` 以外の値は無視される。v5 で削除予定。

state 取得に失敗したときは、`compat=legacy` でも封筒を返す
（`500` / `{ok:false, data:null, error:{code:"INTERNAL"}}`）。旧形式で返すと
`ok:false` は返せても `error` を JSON 化できる保証がないため、失敗の形は新しい封筒に一本化する。

---

## Vector Store Admin（削除済み — d6）

> `POST /api/admin/rebuild/{persona}` は削除済み。

---

## Skills

スキルはグローバル（`${DATA_ROOT}/skills`）とペルソナ専用（`persona/<p>/skills`）の2本。

### `GET /api/skills`

全ペルソナ分のスキル一覧。

### `GET /api/skills/{persona}`

グローバルとペルソナ専用を重ねて返す。同名はペルソナ優先。

## Runtime Settings

### `GET /api/settings`

Get all runtime configuration values with metadata.

### `PUT /api/settings`

Update a runtime setting.

**Request body:** `{ "category": "general", "key": "log_level", "value": "DEBUG" }`

**Auth:** once `general.api_key` is set, **every** `/api/*` route requires
`Authorization: Bearer <key>` (or `?token=<key>` for `EventSource`) and answers
`401 {"detail":"Invalid API key"}` without it. That includes the routes below that
move where the server listens, where embeddings are stored, or which Host/Origin
are trusted — they are the ones that would be catastrophic if the middleware were
bypassed, so `PUT /api/settings` also checks the key itself:

- `server.*`, `mcp_security.*`, `qdrant.*`, `general.persona_dir`
- `general.api_key` itself (old key required to change or clear; minimum 16 chars)

`/static/*` is deliberately exempt: `<script src>` cannot send headers, so gating it
would replace the dashboard's JS with a 401 body and the page could never bootstrap.

Empty `general.api_key` = bootstrap: nothing is gated until a key exists. The
dashboard picks the key up from `?token=<key>` (stored in `localStorage`, then
stripped from the URL) and attaches it to every same-origin `fetch` and `EventSource`.

### `GET /api/settings/status`

Get reload status for runtime settings.

### `GET /api/settings/diagnostics`

Public-deployment security diagnostics (kanban #6). Returns warnings for
configurations that are unsafe once the server is reachable from outside:
public bind without an API key, CORS `*`, plugin enabled with a weak/empty key,
and MCP security open to every Host/Origin.

```json
{"warnings": [{"code": "public_bind_without_api_key", "severity": "error",
                "message": "...", "hint": "..."}]}
```

The dashboard shows them as a banner at the top of the Settings tab. Only codes,
messages and hints are returned — never the configuration values themselves.

---

## Privacy Levels

Memories have a `privacy_level` field that controls dashboard visibility:

| Level | Value | Description |
|-------|-------|-------------|
| `public` | 0 | Visible to all |
| `internal` | 1 | Default — shown in dashboard |
| `private` | 2 | Hidden from dashboard |
| `secret` | 3 | Hidden from all read APIs |

---

## Search quality parameters (ASIST items, 2026-10-04)

`GET /api/search/{persona}` と `memory_search` ツールは以下の検索品質パラメータを共有する:

| 項目 | 説明 |
|------|------|
| dominantTokenKind 別 bm25 バー | OR-fallback 候補のみ適用。`NOUS_SEARCH__INJECTION_MAX_BM25`（default `{bigram: -2.5, word: -5.0}`、正規化スコア）で上書き可 |
| 注入済み記憶排除 | チャット経路で同 turn 注入済みの記憶を結果から除外 |
| all-term exact 保護 | 全語 exact マッチ候補は bm25 バーを必ず通過（boost 1.0） |

mixed クエリ（Sudachi 辞書なし等）では gate は fail-open（無効）。
