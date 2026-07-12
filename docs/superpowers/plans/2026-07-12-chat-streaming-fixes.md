# Chat Streaming Fixes — ストリーミング表示・ツールコール順序・会話リセット修正

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** WebUIチャットの3つのバグを修正する: (1) LLM応答時に`（`だけ表示される (2) 並列ツール実行時のチャットログ表示順がリアルタイムと異なる (3) 会話リセットしてもログが再読み込みされる

**Architecture:** 
- Bug1: ツールコールのSSE yieldタイミングを即時に変更 + DoneEventハンドリング追加
- Bug2: マルチターン応答をイベント列として保存 → 復元時に時系列順でレンダリング
- Bug3: clearChatHistoryのDELETEをawait化 + restoreChatHistoryにガード追加

**Tech Stack:** Python (FastMCP/FastAPI), vanilla JS (chat.js)

---

## ファイル構造

| ファイル | 責務 | 変更 |
|----------|------|------|
| `nous/infrastructure/llm/openai_compat.py` | OpenAI互換プロバイダーのToolCallEvent yieldタイミング修正 | Modify |
| `nous/application/chat/pipeline/inference.py` | ToolCallSSE即時yield + DoneEventログ追加 | Modify |
| `nous/application/chat/session_store.py` | イベント列保存のための `events` フィールド追加 | Modify |
| `nous/application/chat/service.py` | マルチターンメッセージ保存方式変更 | Modify |
| `nous/application/chat/pipeline/context.py` | ターンごとのセグメント追跡用フィールド追加 | Modify |
| `nous/api/http/static/chat.js` | frontend: clearChatHistory await化 + restoreChatHistoryガード + イベント順復元 | Modify |

---

### Task 1: 会話リセットバグ修正（Bug 3）

**優先度最高。修正コスト最小、効果最大。**

**Files:**
- Modify: `nous/api/http/static/chat.js:1122-1152` (clearChatHistory) + `nous/api/http/static/chat.js:1482-1492` (restoreChatHistory) + `nous/api/http/static/chat.js:4-14` (CHAT state)

- [ ] **Step 1: clearChatHistory の DELETE を await 化**

`chat.js:1122-1152` の `clearChatHistory()` 関数を修正する。2つの変更:
1. DELETEリクエストを `await` する（fire-and-forget → 完了待ち）
2. 成功/失敗をトースト通知

```javascript
// Before (L1134-1147):
// Delete server-side session (F3)
const oldSid = getChatSessionId();
if (S.persona && oldSid) {
    fetch("/api/chat/" + encodeURIComponent(S.persona) + "/sessions/" + encodeURIComponent(oldSid), { method: "DELETE" })
    .catch(e => { ... });
}

// After:
const oldSid = getChatSessionId();
if (S.persona && oldSid) {
    try {
        const res = await fetch("/api/chat/" + encodeURIComponent(S.persona) + "/sessions/" + encodeURIComponent(oldSid), { method: "DELETE" });
        if (!res.ok) throw new Error(res.statusText);
    } catch (e) {
        console.warn("[session delete] failed:", e);
        toast("セッション削除失敗: " + e.message, "error");
    }
}
```

- [ ] **Step 2: restoreChatHistory にリセット直後ガードを追加**

`CHAT` オブジェクト（L4-14）に `_justReset: false` フィールドを追加。

`clearChatHistory()` 内で DELETE成功後に `CHAT._justReset = true` をセット。

`restoreChatHistory()` の先頭で `CHAT._justReset` をチェック:
```javascript
if (CHAT._justReset) {
    CHAT._justReset = false;
    return; // リセット直後は履歴を再取得しない
}
```

- [ ] **Step 3: フロントエンド検証**

`browser-testing-with-devtools` スキルを使って実ブラウザで確認:
1. チャットで会話する
2. 会話リセットボタンを押す
3. ウェルカム画面が表示されること
4. ページリロードしても履歴が復元されないこと
5. 新しい会話が正常に開始できること

- [ ] **Step 4: コミット**

```bash
git add nous/api/http/static/chat.js
git commit -m "fix(chat): await DELETE on conversation reset to prevent history reload"
```

---

### Task 2: `（` だけ表示問題（Bug 1）

**ツールコールのSSE yieldを即時化し、ストリーミング中にツール実行中であることをフロントエンドに通知する。**

**Files:**
- Modify: `nous/application/chat/pipeline/inference.py:83-117`
- Modify: `nous/infrastructure/llm/openai_compat.py:134-176`

- [ ] **Step 5: inference.py で ToolCallEvent 受信時に即座に ToolCallSSE を yield**

`inference.py:95-96`:
```python
# Before:
elif isinstance(event, ToolCallEvent):
    pending_tool_calls.append(event)

# After:
elif isinstance(event, ToolCallEvent):
    pending_tool_calls.append(event)
    yield ToolCallSSE(name=event.tool_name, input=event.tool_input, id=event.tool_use_id)
```

`inference.py:115-117` のツールコール一括yieldは削除:
```python
# REMOVE these lines:
# for tc in pending_tool_calls:
#     yield ToolCallSSE(name=tc.tool_name, input=tc.tool_input, id=tc.tool_use_id)
```

- [ ] **Step 6: inference.py で DoneEvent ハンドリング追加**

`inference.py:97-99` の後に `DoneEvent` ハンドリングを追加:
```python
elif isinstance(event, DoneEvent):
    # Provider finished streaming this turn.
    # Log unexpected empty response for debugging.
    if not current_text and not pending_tool_calls:
        logger.warning(
            "InferenceStep: provider finished with empty response (model=%s, turn=%d)",
            config.get_effective_model(),
            turn_ctx.tool_call_count,
        )
```

`DoneEvent` の import を追加（L6のbase importに追加）:
```python
# L6 に DoneEvent を追加
from nous.infrastructure.llm.base import DoneEvent, ErrorEvent, LLMMessage, TextDeltaEvent, ToolCallEvent
```

- [ ] **Step 7: openai_compat.py のツールコール yield をストリーム中に変更**

問題: OpenAI互換プロバイダーではToolCallEventがストリーム完了後に一括yieldされている（L162-174）。
修正: ツール名が判明した時点（最初のツールコールチャンク）で即座にyieldする。ただし引数は不完全なので、全引数が揃った後に完全なToolCallEventを再度yieldする。

よりシンプルな方法: ツール名が判明したら、引数がまだでも不完全なToolCallEventをyieldする（inference.py側で重複排除するため、同じtool_use_idのものはスキップされる）。

```python
# openai_compat.py:144-159 を修正:

if delta.tool_calls:
    for tc_chunk in delta.tool_calls:
        idx = tc_chunk.index
        if idx not in pending_tool_calls:
            pending_tool_calls[idx] = {
                "id": tc_chunk.id or "",
                "name": tc_chunk.function.name if tc_chunk.function else "",
                "args_json": "",
                "yielded": False,  # 初回yield済みフラグ
            }
        if tc_chunk.id:
            pending_tool_calls[idx]["id"] = tc_chunk.id
        if tc_chunk.function:
            if tc_chunk.function.name:
                pending_tool_calls[idx]["name"] = tc_chunk.function.name
            if tc_chunk.function.arguments:
                pending_tool_calls[idx]["args_json"] += tc_chunk.function.arguments
        # ツール名が判明したら即座にyield（初回のみ。引数はまだ空でも可）
        tc_data = pending_tool_calls[idx]
        if tc_data["name"] and not tc_data.get("yielded"):
            tc_data["yielded"] = True
            yield ToolCallEvent(
                tool_name=tc_data["name"],
                tool_input={},  # 引数未確定のため空。後続で完全版が来る
                tool_use_id=tc_data["id"],
            )
```

**注意**: inference.py側で既にyield済みのtool_callを重複排除する必要がある。L122-130の重複排除ロジックは機能名＋引数で重複判定しているため、tool_use_idベースに変更する。

- [ ] **Step 8: inference.py の重複排除を tool_use_id ベースに変更**

`inference.py:119-144`:
```python
# Before: 機能名+引数で重複判定
executed_keys = {
    (tc.get("name", ""), json.dumps(tc.get("input", {}), sort_keys=True, default=str))
    for tc in (turn_ctx.tool_calls_log or [])
}

# After: tool_use_id で重複判定
executed_ids = {tc.get("id", "") for tc in (turn_ctx.tool_calls_log or [])}
pending_tool_calls = [tc for tc in pending_tool_calls if tc.tool_use_id not in executed_ids]
```

同様に同一バッチ内重複排除（L133-144）も tool_use_id ベースに変更。

- [ ] **Step 9: バックエンドテスト実行**

```bash
cd /home/rausraus/code/Nous
pytest tests/ -x -q --tb=short -k "inference or chat" 2>&1 | head -50
```

- [ ] **Step 10: コミット**

```bash
git add nous/application/chat/pipeline/inference.py nous/infrastructure/llm/openai_compat.py
git commit -m "fix(chat): yield tool_call SSE immediately during streaming, handle DoneEvent"
```

---

### Task 3: ツールコール表示順修正（Bug 2）

**マルチターン応答をイベント時系列で保存・復元する。**

**Files:**
- Modify: `nous/application/chat/pipeline/context.py` — ターンセグメント追跡フィールド追加
- Modify: `nous/application/chat/service.py:116-150` — ターンごとに個別メッセージ保存
- Modify: `nous/application/chat/session_store.py:62-79` — メッセージ保存方式変更
- Modify: `nous/api/http/static/chat.js:1522-1601` — 復元時のレンダリング順修正

- [ ] **Step 11: context.py にターンセグメント追跡を追加**

`ChatTurnContext` に `turn_segments: list[dict]` フィールドを追加。
各セグメントは `{type: "text", content: str}` または `{type: "tool_call", name: str, input: dict, id: str, result: any}` の形式。

- [ ] **Step 12: inference.py でターンセグメントを記録**

`inference.py` の while ループ内で:
- `TextDeltaSSE` yield時に「現在のテキストセグメント」を追跡
- `ToolCallSSE` yield時にセグメント区切りとしてテキストセグメントを確定
- `ToolResultSSE` yield時にツールコールセグメントにresultを追加

ループ終了時に残りのテキストセグメントを確定。

```python
# inference.py: ループ冒頭
turn_segments: list[dict] = []
current_text_segment = ""

# TextDeltaSSE yield 時:
current_text_segment += event.content

# ToolCallSSE yield 時:
if current_text_segment:
    turn_segments.append({"type": "text", "content": current_text_segment})
    current_text_segment = ""
turn_segments.append({"type": "tool_call", "name": tc.tool_name, "input": tc.tool_input, "id": tc.tool_use_id})

# ToolResultSSE yield 時:
# 最後のtool_callセグメントにresultを追加
for seg in reversed(turn_segments):
    if seg["type"] == "tool_call" and seg["id"] == tc.tool_use_id:
        seg["result"] = truncated
        break

# ループ終了時:
if current_text_segment:
    turn_segments.append({"type": "text", "content": current_text_segment})

turn_ctx.turn_segments = turn_segments
```

- [ ] **Step 13: service.py でターンセグメントを使って保存**

`service.py:127-134` のセッション保存を変更。`turn_ctx.tool_calls_log` の代わりに `turn_ctx.turn_segments` を使う:

```python
# Before:
session.add("assistant", full_response, get_now(), tool_calls=turn_ctx.tool_calls_log)

# After:
if turn_ctx.turn_segments:
    session.add("assistant", full_response, get_now(), events=turn_ctx.turn_segments)
elif full_response:
    session.add("assistant", full_response, get_now())
```

- [ ] **Step 14: session_store.py の add メソッドで events フィールド対応**

`SessionWindow.add()` (L62-79) で `tool_calls` の代わりに `events` フィールドを受け付ける:

```python
def add(self, role, content, ts=None, tool_calls=None, events=None):
    msg = {"role": role, "content": content}
    if events:
        msg["events"] = events
    if tool_calls:
        msg["tool_calls"] = tool_calls  # 後方互換
    self._messages.append(msg)
    ...
```

- [ ] **Step 15: chat.js restoreChatHistory で events を時系列順にレンダリング**

`restoreChatHistory()` (L1522-1601) のレンダリングロジックを変更:

```javascript
if (msg.role === "assistant" && msg.events?.length) {
    // events フィールドがあれば時系列順にレンダリング
    for (const evt of msg.events) {
        if (evt.type === "text") {
            appendChatMessage("assistant", evt.content, msg.time, true);
        } else if (evt.type === "tool_call") {
            // tool_call と result をまとめてレンダリング
            const div = document.createElement("div");
            div.className = "chat-tool-call done";
            // ... (既存の tool_call レンダリングコードを再利用)
            container.appendChild(div);
        }
    }
} else if (msg.role === "assistant" && msg.tool_calls?.length) {
    // 後方互換: events がない場合は旧方式
    // (既存コード L1526-1558)
}
```

- [ ] **Step 16: テスト実行**

```bash
cd /home/rausraus/code/Nous
pytest tests/ -x -q --tb=short 2>&1 | tail -20
```

- [ ] **Step 17: コミット**

```bash
git add nous/application/chat/pipeline/context.py nous/application/chat/pipeline/inference.py nous/application/chat/service.py nous/application/chat/session_store.py nous/api/http/static/chat.js
git commit -m "fix(chat): save multi-turn responses as event timeline for correct display order"
```

---

## 検証チェックリスト

- [ ] Bug 3: 会話リセット後、リロードしても履歴が復元されない
- [ ] Bug 1: LLM応答時にツールコールが即座に表示され、`（` が単独で長時間表示されない
- [ ] Bug 2: 並列ツール実行時の履歴復元で、テキスト→ツールコール→テキスト→ツールコール の順が維持される
- [ ] 後方互換: events フィールドがない旧形式メッセージも正常に表示される

---

## Chunk 2: 実行優先順位

Task 1 → Task 2 → Task 3 の順で実装する。

各タスク完了後にコミット。Task 1 と Task 2 は独立して実装可能。Task 3 は Task 2 の変更（turn_segments）に依存するため最後に実装する。
