# Minimal B: parentIdツリー構造によるチャット編集・削除のリライト

> **For agentic workers:** REQUIRED: Use subagents for parallel implementation. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** チャットメッセージの編集・削除・ロールバックを、フラット配列+整数インデックスからUUID+parentIdツリー構造に移行し、全バグ（編集消失、インデックス乖離、segments未編集、同時編集競合）を根本解決する。

**Architecture:** Minimal B — parentId adjacency list + 編集のみインプレース上書き + ロールバックはactive_leaf_id変更のみ（非破壊）。3-6ヶ月後に編集をブランチ分岐にアップグレード可能。

**Tech Stack:** Python 3, SQLite, vanilla JS（フロントエンド）, UUIDv7, SSE

---

## 変更サマリ

| ファイル | 変更種別 | 行数見込み |
|---------|---------|-----------|
| `nous/application/chat/session_store.py` | 大幅リライト | ~200行新規, ~100行削除 |
| `nous/api/http/routers/chat.py` | API変更 | ~60行変更 |
| `nous/application/chat/service.py` | 微修正 | ~15行変更 |
| `nous/application/chat/pipeline/post.py` | 微修正 | ~10行変更 |
| `nous/api/http/static/chat/chat-send.js` | ID追加 | ~10行変更 |
| `nous/api/http/static/chat/chat-history.js` | IDベース書換 | ~80行変更 |
| `tests/unit/test_chat_service.py` | テスト更新 | ~150行変更/追加 |

---

## データモデル

### 永続化フォーマット（messagesカラム）

```json
{
    "root_id": "uuid-v7-xxx",
    "active_leaf_id": "uuid-v7-zzz",
    "nodes": [
        {
            "id": "uuid-v7-aaa",
            "parent_id": null,
            "role": "user",
            "content": "こんにちは",
            "segments": null,
            "tool_calls": null,
            "created_at": "2026-07-20T12:00:00+09:00"
        }
    ]
}
```

### timestampsカラム
旧形式（配列）→ 空配列 `[]` に（created_atに統合済みのため）

### 後方互換
`from_db()` で `messages` が array なら旧形式と判定 → 自動マイグレーション：
1. 各メッセージに UUIDv7 を生成、`parent_id` を前メッセージの id に設定
2. `root_id` = 先頭メッセージの id
3. `active_leaf_id` = 末尾メッセージの id

---

## 操作セマンティクス

| 操作 | 旧（flat） | 新（Minimal B） |
|------|-----------|----------------|
| 追加 | `_messages.append(msg)` | `nodes[id]=node`, `active_leaf_id=id` |
| 編集 | インプレース上書き（index） | インプレース上書き（id）←**据え置き** |
| 削除 | `truncate_to(index)` 物理削除 | リペアレンティング: 子の `parent_id` を `msg.parent_id` に付け替え |
| ロールバック | `truncate_to(index)` 物理削除 | `active_leaf_id = id` ←**ポインタ変更のみ** |
| 表示取得 | 配列そのまま | `root_id → active_leaf_id` パス走査 |

---

## 実装タスク

---

## Chunk 1: バックエンド — TreeSessionWindow（コアデータモデル）

### Task 1.1: `TreeSessionWindow` 基本実装

**Files:**
- Modify: `nous/application/chat/session_store.py`

`SessionWindow` を **置き換えずに** 新クラス `TreeSessionWindow` として実装（既存クラスは旧データ読み込み用に一時保持）。段階的に置き換える。

```python
import uuid
import uuid_extensions  # for uuid7()

def _new_msg_id() -> str:
    return str(uuid_extensions.uuid7())

class TreeSessionWindow:
    def __init__(self, max_messages: int = 200, batch_size: int = 10) -> None:
        self._max_messages: int = max_messages
        self._nodes: dict[str, dict] = {}      # id → node dict
        self._root_id: str | None = None
        self._active_leaf_id: str | None = None
        self._db: sqlite3.Connection | None = None
        self._persona: str = ""
        self._session_id: str = ""
        self._persisted_count: int = 0
        self._batch_size: int = batch_size
        self.pending_memory_task: asyncio.Task | None = None
        self.evict_callback: Callable[[list[dict]], None] | None = None

    # ── コア操作 ──

    def add(self, role, content, ts=None, tool_calls=None, segments=None) -> str:
        """ノードを追加し、active_leaf_id を更新。戻り値は生成された msg_id。"""
        ...

    def get_active_path(self) -> list[dict]:
        """active_leaf_id から root_id まで parent_id を辿り、逆順の表示用リストを返す。"""
        ...

    def edit_message(self, msg_id: str, new_content: str) -> dict | None:
        """指定IDのメッセージ content をインプレース更新（Minimal）。"""
        ...

    def delete_message(self, msg_id: str) -> dict | None:
        """ノードを削除。子ノードの parent_id を削除対象の parent_id に付け替え（リペアレンティング）。
        active_leaf_id が削除対象以下なら、parent_id に巻き戻す。"""
        ...

    def rollback_to(self, msg_id: str) -> dict | None:
        """active_leaf_id を msg_id に差し替えるのみ（非破壊）。"""
        ...

    def get_message_by_id(self, msg_id: str) -> dict | None:
        """ID指定でノードを取得。"""
        ...

    # ── 永続化 ──

    def _persist(self) -> None:
        """nodesをJSONダンプし messages カラムに保存。timestamps は空配列（created_atに統合）。"""
        ...

    def flush(self) -> None:
        self._persist()

    # ── DB ロード ──

    @classmethod
    def from_db(cls, db, persona, session_id, max_messages=200) -> 'TreeSessionWindow | None':
        """DBロード + 旧形式自動マイグレーション。"""
        ...

    # ── LLM用表示 ──

    def get_labeled_messages(self, now=None) -> list[LLMMessage]:
        """get_active_path() の結果を LLMMessage リストに変換。"""
        ...

    def get_last_assistant_content(self) -> str | None:
        """アクティブパス内の直近アシスタント発言を返す。"""
        ...

    def get_message_count(self) -> int:
        """アクティブパスのメッセージ数を返す。"""
        ...

    def __len__(self) -> int:
        return len(self.get_active_path())
```

**重要ポイント:**
- `add()` は UUIDv7 を生成し、戻り値として返す（サービス層で利用）
- `get_active_path()` が表示用配列を返す — これが `get_labeled_messages()` と `get_messages()` のデータ源
- `delete_message()` のリペアレンティング: 全ノード走査で `parent_id == msg_id` なノードを探し、`parent_id` を `msg.parent_id` に更新
- `rollback_to()` は `active_leaf_id` 差し替えのみ。**データは一切消さない**
- `from_db()` の旧形式検出: `isinstance(messages, list)` → マイグレーション

---

### Task 1.2: `SessionManager` 更新

**Files:**
- Modify: `nous/application/chat/session_store.py`

`SessionManager` を `TreeSessionWindow` を使うよう更新:

```python
class SessionManager:
    # _sessions の型を TreeSessionWindow に変更
    def get_or_create(...) -> TreeSessionWindow:
        ...
    
    @staticmethod
    def get_messages(db, persona, session_id) -> list[dict]:
        """active_path をフロントエンド用にシリアライズ。各エントリに 'id' フィールドを含める。"""
        ...
```

`get_messages()` の戻り値に `"id"` フィールドを追加（フロントエンドの `data-msg-id` 用）。

---

### Task 1.3: スキーマ変更

**Files:**
- Modify: `nous/application/chat/session_store.py` の `_CHAT_SESSIONS_SCHEMA`

テーブル構造はそのまま（persona, session_id, messages, timestamps, updated_at）。
`messages` カラムの内容が object になるだけなのでDDL変更不要。`timestamps` カラムは空配列 `[]` で保存。

---

## Chunk 2: APIレイヤー

### Task 2.1: PUT `/messages/{msg_id}` 更新

**Files:**
- Modify: `nous/api/http/routers/chat.py:309-368`

**変更点:**
1. パスパラメータ名を `msg_index` → `msg_id` に
2. `int()` 変換を削除（IDは文字列）
3. `window.update_message()` → `window.edit_message(msg_id, new_content)`
4. `SessionWindow` import → `TreeSessionWindow`

```python
@mcp.custom_route("/api/chat/{persona}/sessions/{session_id}/messages/{msg_id}", methods=["PUT"])
async def update_chat_message(request: Request) -> JSONResponse:
    # msg_id = request.path_params.get("msg_id", "")  ← int変換不要
    # window.edit_message(msg_id, new_content.strip())
```

### Task 2.2: POST `/rollback` 更新

**Files:**
- Modify: `nous/api/http/routers/chat.py:370-446`

**変更点:**
1. リクエストボディ: `keep_until` → `from_id`
2. `window.truncate_to()` → `window.rollback_to(msg_id)`
3. レスポンスに `active_leaf_id` を追加
4. `removed_user_text` ロジック: 削除時のみ有効

```python
@mcp.custom_route("/api/chat/{persona}/sessions/{session_id}/rollback", methods=["POST"])
async def rollback_chat_session(request: Request) -> JSONResponse:
    """ロールバック: active_leaf_id を from_id に差し替え（非破壊）。"""
    # body: {"from_id": "uuid-..."}
    from_id = body.get("from_id", "")
    # ...
    result = window.rollback_to(from_id)
    remaining = SessionManager.get_messages(db, persona, session_id)
    return JSONResponse({
        "active_leaf_id": from_id,
        "remaining_messages": remaining,
    })
```

### Task 2.3: GET `/sessions/{id}/messages` 更新

**Files:**
- Modify: `nous/api/http/routers/chat.py:272-287`

`SessionManager.get_messages()` の戻り値形式変更に対応。各メッセージに `id` フィールドが含まれるようになる。

---

## Chunk 3: サービスレイヤー + パイプライン

### Task 3.1: `ChatService.chat()` — `add()` 戻り値活用

**Files:**
- Modify: `nous/application/chat/service.py`

**変更点:**
1. `session.add()` の戻り値（msg_id）を受け取る
2. `turn_ctx.user_msg_id` と `turn_ctx.assistant_msg_id` に保存
3. `session.flush()` はそのまま

```python
# service.py:113 → 変更
user_msg_id = session.add("user", turn_ctx.user_message, now)
turn_ctx.user_msg_id = user_msg_id

# service.py:129 → 変更
assistant_msg_id = session.add(
    "assistant", full_response, get_now(),
    tool_calls=turn_ctx.tool_calls_log if turn_ctx.tool_calls_log else None,
    segments=turn_ctx.segments if turn_ctx.segments else None,
)
turn_ctx.assistant_msg_id = assistant_msg_id
```

### Task 3.2: `ChatTurnContext` — メッセージIDフィールド追加

**Files:**
- Modify: `nous/application/chat/pipeline/context.py`

`ChatTurnContext` に以下を追加:
```python
user_msg_id: str | None = None
assistant_msg_id: str | None = None
```

### Task 3.3: `PostProcessStep` — doneイベントにID追加

**Files:**
- Modify: `nous/application/chat/pipeline/post.py`

`done` イベントに `user_msg_id` と `assistant_msg_id` を含める。フロントエンドがDOMに `data-msg-id` を設定するのに使う。

---

## Chunk 4: フロントエンド

### Task 4.1: `appendChatMessage` — `data-msg-id` 埋め込み

**Files:**
- Modify: `nous/api/http/static/chat/chat-send.js:18-116`

**変更点:**
1. `dataset.msgId` をパラメータとして受け取れるようにする
2. ストリーミング完了後、`done` イベントの `user_msg_id` / `assistant_msg_id` を使ってDOM要素を更新

```javascript
function appendChatMessage(role, content, timeStr, isMarkdown, msgId) {
    // ...
    div.dataset.msgId = msgId || "";  // ストリーミング中は空、done後に更新
    // ...
}
```

### Task 4.2: `_createAssistantDiv` — `data-msg-id` 埋め込み

**Files:**
- Modify: `nous/api/http/static/chat/chat-send.js:156-217`

`dataset.msgId` を空で初期化。done イベント受信時に `assistant_msg_id` を設定。

### Task 4.3: `chatSend` — done イベント処理更新

**Files:**
- Modify: `nous/api/http/static/chat/chat-send.js:501-556`

`done` イベントに `user_msg_id`, `assistant_msg_id` が含まれている場合:
1. 最新の `.chat-msg.user` の `dataset.msgId` を設定
2. `assistantDiv` の `dataset.msgId` を設定

### Task 4.4: `restoreChatHistory` — `data-msg-id` 設定

**Files:**
- Modify: `nous/api/http/static/chat/chat-history.js:264-543`

履歴復元時に、サーバーから返された各メッセージの `id` フィールドを `data-msg-id` として設定する。

全 `.chat-msg` 要素に対して:
```javascript
div.dataset.msgId = msg.id || "";
```

### Task 4.5: `editChatMessage` — IDベース書換

**Files:**
- Modify: `nous/api/http/static/chat/chat-history.js:150-259`

**変更点:**
1. 引数: `editChatMessage(msgId)` — msgIndex ではなく msgId
2. 要素選択: `'.chat-msg.user[data-msg-id="' + msgId + '"]'`
3. APIパス: `/messages/` + msgId
4. `rollbackChat(msgId, true)` — keep_until ではなく from_id として

### Task 4.6: `rollbackChat` — IDベース書換

**Files:**
- Modify: `nous/api/http/static/chat/chat-history.js:89-145`

**変更点:**
1. 引数: `rollbackChat(fromId, shouldResend)`
2. リクエストボディ: `{from_id: fromId}`
3. DOM削除: `data-msg-id` ベースではなく、レスポンスの `remaining_messages` 配列を元にDOMを**完全再構築**（これで全インデックス乖離バグが解決する）
4. `removed_user_text` → 削除削除時の処理として分離

### Task 4.7: `deleteChatMessage` — IDベース書換

**Files:**
- Modify: `nous/api/http/static/chat/chat-history.js:592-650`

**変更点:**
1. 引数: `deleteChatMessage(msgId)`
2. 削除確認: IDベースで後続メッセージ数を算出（`get_active_path()` で位置特定）
3. 削除実行: DELETE `/messages/{msg_id}` エンドポイントを新設する or rollback を使用
4. DOM再構築: レスポンスの `remaining_messages` で完全再構築

### Task 4.8: アクションボタン — msgId バインド

**Files:**
- Modify: `nous/api/http/static/chat/chat-send.js:55-115`
- Modify: `nous/api/http/static/chat/chat-send.js:173-216`

編集・削除・再生成ボタンの `onclick` ハンドラに `msgIndex` の代わりに `msgId` を渡す。

---

## Chunk 5: テスト

### Task 5.1: `TreeSessionWindow` 単体テスト

**Files:**
- Modify: `tests/unit/test_chat_service.py`

新規テストクラス `TestTreeSessionWindow`:

```python
class TestTreeSessionWindow:
    def test_initial_empty(self): ...
    def test_add_returns_msg_id(self): ...
    def test_add_creates_chain(self): ...
    def test_get_active_path_returns_ordered_list(self): ...
    def test_edit_message_updates_content(self): ...
    def test_edit_message_returns_none_for_unknown_id(self): ...
    def test_delete_message_repaints_children(self): ...
    def test_delete_message_updates_active_leaf(self): ...
    def test_rollback_changes_active_leaf_only(self): ...
    def test_rollback_preserves_all_nodes(self): ...
    def test_get_labeled_messages_uses_active_path(self): ...
    def test_from_db_migrates_old_flat_format(self): ...
    def test_persist_and_reload(self): ...
```

### Task 5.2: 既存テストの更新

**Files:**
- Modify: `tests/unit/test_chat_service.py`

`SessionWindow` を `TreeSessionWindow` に置き換え。テスト構造が変わるため、以下のテストは要書き換え:
- `TestSessionWindow.test_initial_empty` → 移行
- `TestSessionWindow.test_add_and_retrieve` → `len(win)` を `len(win.get_active_path())` に
- `TestSessionWindow.test_max_messages_eviction` → ツリーでもmax_messages制限が働くか
- `TestSessionWindow.test_get_labeled_messages_*` → アクティブパスベースに
- `TestSessionWindow.test_flush_persists_to_sqlite_immediately` → 新フォーマット対応

### Task 5.3: `from_db` マイグレーションテスト

**Files:**
- Modify: `tests/unit/test_chat_service.py`

旧形式のフラット配列を SQLite に手動で INSERT し、`from_db()` で読み込んだら適切にマイグレーションされていることを確認。

---

## Chunk 6: セッションイベント統合

### Task 6.1: `SessionManager.delete_session` 更新

**Files:**
- Modify: `nous/application/chat/session_store.py`

既存の `delete_session` はそのまま（persona+session_id で行削除なのでデータモデル変更に影響されない）。

---

## 依存関係グラフ

```
Chunk 1 (TreeSessionWindow) 
    └── Chunk 2 (API) ──┐
    └── Chunk 3 (Service) ──┤
                            ├── Chunk 4 (Frontend)
                            └── Chunk 5 (Tests)
```

- Chunk 1 → 2 と Chunk 1 → 3 は**並列実行可能**（同じファイルだが変更箇所が異なる）
- Chunk 4 は Chunk 2 のAPI変更完了後に着手
- Chunk 5 は Chunk 1 完了後に着手

---

## ロールバック後の再生成フローの修正（Bug #1 根本解決）

**現行の問題**: `editChatMessage` で編集 → `rollbackChat(msgIndex, true)` が編集したメッセージ自身も削除してしまう

**Minimal B での解決**: 
1. `edit_message(msg_id)` はインプレースで content を更新
2. 編集後、後続メッセージを再生成したい場合は `rollback_to(msg_id)` → `active_leaf_id` を編集メッセージに巻き戻す → ユーザー入力を復元 → 自動送信
3. 編集されたメッセージは active_path に残る（ロールバック先が編集メッセージ自身なので、それを含むパスが表示される）

---

## 実装順序

1. **Chunk 1** — `TreeSessionWindow` を実装し、`SessionWindow` と共存させる
2. **Chunk 3** — `ChatService` とパイプラインを更新（並列可）
3. **Chunk 2** — API エンドポイント更新（Chunk 1 依存）
4. **Chunk 5** — テスト更新（Chunk 1 依存）
5. **Chunk 4** — フロントエンド更新（Chunk 2 依存）
6. **統合テスト** — 全テスト実行 + 手動ドッグフーディング
7. **Chunk 6** — クリーンアップ（旧 SessionWindow 削除）

---

## 注意点

- **UUIDv7**: `uuid_extensions` パッケージが既にインストールされているか確認。なければ `pip install uuid7`。
- **旧SessionWindow共存**: Chunk 1 実装中は `SessionWindow` を削除せず、`TreeSessionWindow` と並存させる。全テスト移行完了後に削除。
- **旧形式マイグレーション**: `from_db()` の初回呼び出し時に自動的に行われる。ユーザーの既存会話データは失われない。
- **timestamps カラム**: 旧形式ではメッセージと並列の配列だったが、新形式では `created_at` に統合。DBの timestamps カラムには空配列を保存。
