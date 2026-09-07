# 内省エンジン ＋ チャット分離（SSEハブ）設計書

**状態**: ユーザー方針決定済み（2026-09-07、3デシジョン承認）→ スペック確認待ち
**前提仕様**: 2026-09-07-rem-monologue-design.md（独り言 M1-M3 実装済み・実機検証済み）

## 0. ユーザー要求と決定

| # | 要求 | 決定 |
|---|------|------|
| 1 | 独り言が発火フィードに出るのは変。チャット欄へ | **チャット欄のみ**（発火パネルから除外、wiring emit は輸送手段として維持） |
| 2 | 独り言クリックで中身モーダルが欲しい | 💭バブル→内容モーダル（既存語彙・keyless ガード追加） |
| 3 | 独り言で感情・身体状態が変動すべき | 独り言LLM出力に delta を載せて persona state へ適用 |
| 4 | ジャッジLLM（キャラ逸脱警告）を脳シミュレータに融合し内省エンジンへ | **毎ターン判定廃止→アイドル時一括**（REM drain 後） |
| 5 | チャット送信後ブラウザを閉じるとメッセージが消える。処理は継続しログも残せ | **サーバー内タスク化＋即時flush** |
| 6 | 複数環境の WebUI をリアルタイム同期 | **SSEハブ**（チャットdelta・状態・設定を配信） |
| 7 | 発火詳細モーダルがテーマ不一致 | ハードコード色→テーマ変数、開閉をクラストグルへ |

## 1. 独り言の配置と詳細モーダル（E1）

- **発火パネル除外**: `chat-memory-panel.js` の JS 側 `WIRING_KINDS` マップから `monologue` を削除（`pushWiringEvent` は未知 kind を弾くので、サーバー emit（enrichment_worker.py:158）は**無変更**）。チャット側の "wiring-chat" ストリーム消費（chat-send.js `handleMonologueWiring`、seq 重複排除済み）は維持。
- **💭バブル→モーダル**: バブル summary クリック → `N.Components.memModal.openMemory({content: text, tags: ["monologue"]})`。`mem-modal.js` に **keyless ガード**を追加（`mem.key` 無しの場合 Edit/Delete を非表示・非活性。mem-modal.js:147-160 が key 参照する箇所）。
- **バブル復元**（前回の未決事項・本設計で採用）: チャット履歴読み込み時に `GET /api/session-events?event_type=brain.monologue` 相当で brain.monologue を取得し、💭バブルを履歴順に復元描画。サーバー再起動後も見える。**表示のみ・履歴配列非混入**は据え置き。

## 2. 内省エンジン（E2）

毎ターン `judge_character`（post.py:207-226、`config.character_judge_enabled` デフォルトON）を廃止し、REM drain 後に一括実行する。

### フロー（EnrichmentWorker._run_cycle drain 完了後フック → `_maybe_introspect(drained)`）

1. **ガード**: `brain_introspection_enabled`（session_config 新キー、デフォルト True）＋ generator 解決済み。repo 未達は skip（独り言と同一パターン）。
2. **ターン取得**: `chat_sessions` から直近 N メッセージ（user+assistant のみ、直近12件・合計8000字cap）。前回内省以降のみ対象 — 前回時刻は `session_events` の `event_type="brain.introspection"` 最新タイムスタンプ（無ければ全対象）。新規ターン0件なら skip。
3. **単一 LLM 呼び出し**: 新モジュール `nous/application/chat/introspection.py`。プロンプト（brain 解決鎖・MonologueGenerator と同一 provider）入力＝直近会話＋記憶強化結果（drained memory contents）＋system_prompt。出力 JSON:
   ```json
   {"monologue": "一人称独り言", "violation": "...|null", "violation_detail": "...",
    "reflection": "一人称反省文|null", "emotion": {"emotion": "joy", "emotion_intensity": 0.6}|null,
    "body_state": {"fatigue": 0.3, "warmth": 0.5, "arousal": 0.2}|null}
   ```
   emotion は正典25語のみ・intensity 0.0-1.0。body 数値は絶対値（現行 MemoryLLM プロンプト規約準拠）。
4. **適用**（各 try/except + debug、worker 停止しない）:
   - `emotion`/`body_state` 非 null → `ctx.persona_service.update_emotion` / `update_physical_state`（**直接 repo 書き込み禁止**。decay と衝突しない `last_state_update` 更新版サービス経由）。
   - `violation` 非 null → 反省メモリを `create_memory(content=reflection, tags=["character_drift","introspection"], importance 0.8)`。直近の character_drift と同文なら skip（重複禁止）。context_loader の「前回の反省」セクションが自動表示。
   - monologue → 従来通り session_events（brain.monologue）＋wiring emit。**`brain_monologue_enabled=false` の場合は monologue の保存・emit・表示を skip するが、判定と状態適用は実行する**（独り言トグルと内省トグルは独立）。
   - `brain.introspection` イベントを session_events に記録（メタ: violation 有無・適用内容）。
5. **post.py**: judge 呼び出しと `_with_drift` を削除（MemoryLLM は drift=None で呼ぶ）。`character_judge_enabled` は消費停止（config キー自体は後方互換で残置）。

## 3. チャット分離： サーバー内タスク＋SSEハブ（E3）

### 現状の病巣
POST → StreamingResponse → `ChatService.chat` generator が**応答配信と処理を結合**。ブラウザ切断で generator が aclose → 応答未保存・PostProcess 未完・（batch_size=10 のため）user メッセージも消失。

### 設計
- **TurnHub**（新規 `nous/application/chat/turn_hub.py`）: persona 毎。`publish(persona, payload)` → リングバッファ（maxlen=600、単調 seq）＋購読クライアントの `asyncio.Queue(maxsize=256, drop-oldest)` へ即時 push。`snapshot_after(last_seq)` で再接続リプレイ。1 persona 同時 1 ターン（実行中の新 POST は 409）。
- **ChatService**: 既存 `chat` generator は**無変更**。新規 `chat_turn()` = `asyncio.create_task` で generator を消費し、各イベントを `hub.publish(evt ペイロード)` に tee。保存パス（service.py:272/291 の session.add）はタスク内で完結→切断の影響ゼロ。
- **Router**（chat_stream.py）:
  - `POST /api/chat/{persona}` → `{message, session_id, debug}` 受けて turn 登録 → **202 `{turn_id}` 即時返却**（フロントと同時変更）。
  - `GET /api/chat/{persona}/events?last_seq=N`（新規SSE）→ 接続時バッファリプレイ → ライブ push。keepalive 15s、`is_disconnected()`（既存パターン events.py:126）。
  - ハブは `turn_started {user_message, user_msg_id}` を合成発行（他クライアントが即座に user バブル表示できる）。
- **フロント**（chat-send.js）: fetch-stream 読み取り → ハブSSE購読に置換。既存イベントハンドラ（text_delta/tool_call/done/debug 等）は**流用**、供給源が変わるだけ。送信は POST→202→SSE 購読確認。409 はトースト。再接続時 last_seq 送り delta 再構築（欠落大なら done の full_response で一括再構築）。
- **複数クライアント**: 全クライアントが同一ハブ購読 → delta・ツール・done が同時表示。done で履歴再読込トリガー。
- **設定同期**: `chat_management.save_chat_config` 成功時 `EventBus.publish("config.updated", {persona})`。フロント sse.js ハンドラ＝設定パネルが開いていれば debounced 再読込。
- **注記**: TTS 字幕 kickoff（chat_stream.py:125）はタスク側に残る。セッション TTL 7日削除（session_manager.py:28）は本件スコープ外（別途棚卸し）。

## 4. 軽微修正（E4）

- `tree_session.add()` → **毎回 `_persist()`**（ターン頻度は低く JSON は小さい。batch=10 を撤去）。
- `components.css:1418-1419` `.wiring-detail-chip` の `rgba(191,90,242,…)` → テーマ変数（`color-mix(in srgb, var(--accent-purple) 12%, transparent)` 等）。
- `chat-memory-panel.js:952/969` wiring-detail-overlay の `style.display` 開閉 → `.ov-modal-overlay.active` クラストグル（components.css:990-994 の規約）。
- `panel-detail-overlay` 初回 open の transition 不発 → append と `.show` の間に強制 reflow（`void overlay.offsetWidth`）。

## 5. テストと検証

- **unit**: TurnHub（publish/subscribe/リプレイ/溢れドロップ/409直列化）/ chat_turn 202 フロー（fake generator・切断なし完了）/ introspection（ターンフィルタ・前回以降判定・反省重複skip・state適用・ガード系）/ monologue JSON パース / tree_session 即時 persist / mem-modal keyless / パネル monologue 除外 / chat-send ハブ購読・再接続リプレイ / 設定同期。
- **実機**（Playwright）: ①送信→ブラウザ閉→再オープンでメッセージ・応答が揃って表示 ②2クライアント同時表示 ③アイドル→内省実行→💭バブル・感情/身体変動・反省ファクト確認 ④独り言バブルクリック→モーダル ⑤再会注入 `<monologue_context>`（前回未実施分）⑥テーマ切替でモーダル色確認。
- GATE: pytest 全体 / vitest / mypy 新規0 / ruff → REVIEW(#081) → GATE → RECORD。

## 6. レーン構成

| レーン | 担当 | スコープ | 依存 |
|--------|------|----------|------|
| fix-4（再利用） | #011 | E2 内省エンジン（introspection.py/session_config/enrichment_worker/post.py） | なし |
| fix-5（新規） | #011 | E3 ハブ（turn_hub.py/chat_stream.py/service.py wrapper/chat_management.py） | なし（E2 とファイル分離） |
| des-5（再利用） | #057 | E1 全部＋E4＋E3フロント（chat-send 置換は E3 バックエンド着地後） | fix-5（フロント部分のみ） |
| ora-3（再利用） | #081 | REVIEW（実装後） | 全レーン |
