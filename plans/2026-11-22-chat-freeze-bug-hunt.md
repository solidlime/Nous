# チャット凍結バグハント — 全件修正計画（2026-11-22）

対象: ユーザー報告「メッセージを送ると記憶処理中のまま固まる。リロードすると表示される」
＋ ドッグフーディングで洗い出した全バグ＋devtool console エラー撲滅。
kanban #136–#142。前提コード: origin/main 387c27b9（tree clean）。

## 再現メカニズム（実機・コード双方で検証済み）

- クライアント描画は POST /api/chat/{p} の応答ではなく **共通 hub ソケット**
  GET /api/chat/{p}/events の `id: <seq>` で行う（turn.js `_handleHubMessage` の
  `seq <= _chatLastSeq` ゲート＋サーバ chat_stream.py `if seq <= last: continue`）。
- TurnHub の seq は**メモリ内カウンタ**。コンテナ再起動で 1 に戻る。
- 再起動をまたいだタブは `_chatLastSeq`（例: 719）を保持したまま再接続するため、
  新しいイベント（seq 1..N）が二重フィルタで全捨て → done が永遠に来ない →
  `CHAT.streaming=true` のまま「記憶処理中...」で固まり送信ボタンも消えたまま。
  リロードすると `_chatLastSeq=0` からやり直し履歴が見える＝ユーザー症状と完全一致。
- 実機 dogfood（nas:26262, browser-use）で別ルートの固まりも確認:
  done 後の `memory_activity` で `turn-events.js:140` が `ReferenceError:
  _memoryActivityTimer is not defined` を投げ、ステータス「ちょっと考えてる…」が残留。

## 修正（バッチ構成）

### B1 クライアント（static/chat/send/*.js, core/api.js, chat-tts-stream.js）
1. **turn-events.js**: `var _memoryActivityTimer = null;` を復活（#138）。
   done 後ステータスの 30 秒フォールバック解除も追加。
2. **turn.js**: epoch 対応（#136/#137）
   - `_chatEpoch` 追加。`_handleHubMessage` で `id` を `<epoch>:<seq>` として parse、
     epoch 変化で `_chatLastSeq=0` にリセット。URL は `last_seq=<epoch>:<seq>`
     （epoch 未取得時は従来通りの数値のみ）。
   - `onError` → `_sawDrop`、`onOpen`（drop 後）→ `_reconnectedAt` 記録。
     epoch 変化イベント到着時に `_turn` が残留し `t.startedAt < _reconnectedAt`
     なら orphan 回復（endTurnSession + history.restore + toast）。
   - watchdog: `_beginTurnSession` で 5 秒 interval、無イベント 300 秒で回復。
     `_handleHubMessage` 毎に `_lastEventAt` 更新、`_endTurnSession` で解除。
   - 再接続直後に _turn が生きていれば epoch probe（B2 の endpoint）を行い、
     変化していれば即 orphan 回復（イベント待ち不要）。
3. **api.js**: `opts.suppressErrorToast` 指定時は `console.error` も出さない（#139）。
4. **chat-tts-stream.js**: 503 を一度受けたら `_engineDown=true` で以後スキップ、
   初回のみ warn（#140）。

### B2 サーバ（turn_hub.py, chat_stream.py）
5. TurnHub に `self.epoch = uuid.uuid4().hex[:12]`。プロセス単位・全 persona 共通。
6. `chat_event_stream`: `id: {epoch}:{seq}` 形式で送出。`chat_events` は
   `last_seq` を `<epoch>:<seq>` でも受付け、epoch 不一致なら 0 扱い（全 ring 再生）。
   生 int は従来通り（旧クライアント互換）。
7. epoch probe 用に `GET /api/chat/{p}/events/epoch` → `{"epoch": "..."}` を追加。

### B3 Qdrant（#141）
8. `vector_index.py async_drop_memories`: prefix `""` → `"memory_"`。
9. `scripts/cleanup_orphan_vectors.py`: memory_<persona> の point id で
   SQLite memories に存在しないものを掃除（既定 dry-run, --apply）。
   実機コンテナで --apply 実行まで行う。

### B4 テスト
- pytest: epoch 付き id 送出・last_seq epoch 不一致→全再生・TurnHub.epoch 存在。
  （既存 test_turn_hub.py / chat_stream 系テストに追加）
- vitest(chat-send.test.js): ①古い epoch のイベントは基線リセットを起こさない/
  新 epoch で再開できる ②再接続 URL に epoch 付き last_seq ③memory_activity で
  例外なくステータス解除＋loadCommitments（ReferenceError 回帰）
  ④watchdog 300 秒で回復（fake timers）。
  api.js / tts-stream の静音化は既存テストファイルに追記（あれば。無ければ最小新規）。

### B5 デプロイ＋実機検証（#142）
10. main push → ghcr イメージ再ビルド → Portainer 再デプロイ。
11. ブラウザ dogfood: 送信→応答・console 完全 clean・done 後ステータス解除。
    コンテナ再起動しながらタブ維持→送信→**固まらない**ことを実機確認。
    テスト記憶を作って削除→Qdrant 404 が出ない・ベクトルが消えることを確認。

### B6 REVIEW / RECORD
12. ルアン・メェイ REVIEW → PASS 後にコミット確定・RECORD 記憶。

## 非対象（やらないこと）
- wiring-stream（/api/memory/wiring/stream）は別系統の seq/buffer で凍結しない。
  手を入れない。
- MCP プールのターン毎再構築は前回の調査で設計判断（B6 で扱う範囲外）。
- TTS エンジンそのもの（192.168.50.150:8088 が落ちている）は環境問題。
  クライアントの静音化のみ。

---

## 追記（2026-11-22）: 根因 #2 — ブラウザ接続枠枯渇

bf31670a デプロイ後の実機 dogfood で、epoch 修正後に**まだ**固まる局面を発見。
実測で根因を特定した:

- ブラウザの origin 当たり接続枠（HTTP/1.1 で 6）は**全タブで共有**。
- 各タブは main SSE + chat-events + (memory panel 開時) wiring + (graph 開後
  残留) graph-flash を掴む。2 タブ × 3 本で枯渇。
- 枯渇下の新規 EventSource は readyState 0 のまま**無音**（open も error
  も fire しない — TCP 接続が受け入れられず queue に入る）。
  古いタブを閉じた 12 秒後に繋がった実測で因果確定。
- サーバ側は正常（ring に done が入っている）。クライアント受信問題。

### 対策（3 層）
1. **裏タブ解放（一次）**: sse.js に hidden-tab socket policy。`closeOnHidden`
   を持つ stream（main/wiring/graph-flash、chat-events は turn 進行中のみ
   例外扱い）は裏タブ化で切断、表面復帰で url() ゲート経由で再接続。
   backoff timer が hidden 中に発火する抜け道も塞いだ。
2. **stuck-connect watch（二次）**: 送信後 4 秒毎に chat-events を確認し、
   open しなければ closeOnHidden ストリームの open socket を
   wiring → main → その他の順で「試行ベース」で譲り受ける。
   backoff 再接続待ち（自力復帰）には介入しない。候補を使い切ったら
   toast で利用者に案内。切った物はタブ切替（visibilitychange）で復帰。
3. **生成物同期の恒久化**: shell.js は build-css.mjs の生成物 — sse.js を
   編集しても再生しないと本番に届かない（レビュー #1 の指摘）。
   `--check` を CI frontend job に追加し再発防止。

### 検証
- vitest 427/427（裏タブ解放・試行ベース連鎖・backoff 非介入の 3 テスト追加）
- lint:js / lint:css / build-css --check 全緑
- 実機: 2 タブ枯渇を再現 → 古いタブを閉じると即復帰（before/after で確認済み）
