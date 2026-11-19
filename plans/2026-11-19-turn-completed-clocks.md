# turn.completed が「最新対話時間」の時計を更新しない問題の修正

## 背景（洗い出し結果 2026-11-19）

pi 経由の対話は `nous-events` 拡張から `turn.completed` として ingest されるが、
「最新対話時間」を表す 3 系統の時計のどれも更新しない:

| 時計 | 更新元 | pi 経由で更新されるか |
|---|---|---|
| A5. `PersonaState.last_conversation_time` | PostProcessStep (Web チャット turn 終了時) / `tool.called` / `get_context`・`session_begin` | ❌ turn.completed では更新されない |
| B. `last_user_message_at` (chat.message MAX) | `chat/service.py:284` のみ | ❌ 一切されない |
| C. `last_activity_at` (chat.message + chat.llm_response MAX) | 同上 | ❌ されない |

結果: pi で何時間対話・作業していても、proactive worker は「放置」と判断して
自発発言の判断に入入るし、再会表示（REUNION_GAP_SECONDS=900）・感情減衰・
circadian drift も「対話が無い」側に進む。turn.completed は既に記憶抽出
（HOOK_EXTRACTION_EVENT_TYPES）と THEM ブロック（prompt.py:55）で「対話」と
して扱われているので、時計に加算するのは設計意図（spec A4「idle 判定は対話のみ」）に沿う。

## 変更点

### 1. `nous/infrastructure/sqlite/session_event_repo.py`
- `last_user_message_at`: SQL を `(event_type='chat.message' AND internal 接頭辞除外) OR event_type='turn.completed'` の MAX にする。
  turn.completed は pi 由来（UUID セッション ID）のみで internal 接頭辞を持たないため除外不要。
- `_IDLE_ACTIVITY_EVENT_TYPES` に `"turn.completed"` を追加（`last_activity_at` に効く）。
  docstring も更新（spec A4 の趣旨: 対話のみ。worker 内部イベントは従来どおり除外）。
- `proactive_worker.py` の docstring「chat.message のみ」の記述が `idle_minutes()` の
  docstring にあるため、1 行だけ修正してよい（ロジック変更は repo 側で完結）。

### 2. `nous/api/http/routers/chat/events.py`（ingest ハンドラ）
- events 列に `turn.completed` を 1 件でも含む場合、`ctx.persona_service.record_conversation_time(persona)` を 1 回呼ぶ。
  - `session.stopped` 判定 (step 8) と同じ `any(...)` パターンで判定。
  - 失敗は `logger.warning` 1 行で握る（既存の `record_conversation_time` 呼び出しと同じ慣行）。
  - 「現在時刻」を記録する（record_conversation_time の契約）。turn.completed の
    timestamp は flush 時点なので遅延は数秒〜1ターン分で、問題ない。

### 3. テスト
- `tests/unit/test_session_event_last_activity.py` に追加:
  - turn.completed が `last_user_message_at` / `last_activity_at` に数えられること
  - `chat.message` 側は internal 接頭辞（self: 等）の除外が従来どおり効くこと
    （turn.completed を足しても回帰しないこと）
- `tests/unit/test_events_ingest_body.py`（または `test_plugin_auth` の `_mock_context` 環境）に追加:
  - turn.completed を含む ingest で `persona_service.record_conversation_time` が
    1 回呼ばれること（mock の呼び出し検証。`_mock_context` に persona_service が
    無ければ SimpleNamespace 等で足す）

## 触ってはいけないファイル
- `pi/extensions/nous-events.ts`（送信側は変えない）
- `nous/application/workers/*`（worker のロジック変更は不要。repo クエリ側で完結）
- `nous/application/chat/pipeline/*`（Web チャット経路は既に正しく更新される）
- `docs/*.md`（idle 判定の記載は docs に無いことを確認済み。docstring 同期のみ）

## 検証
- `pytest tests/unit/test_session_event_last_activity.py tests/unit/test_events_ingest_body.py tests/unit/test_proactive_worker.py -q`
- `mypy` / `ruff`（変更ファイル分）
