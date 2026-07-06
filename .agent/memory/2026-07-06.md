# MEMORY

## T11: body_state_history complete (2026-07-01)
- Implementation was already in place (table, repo methods, service, body_decay recording, context display, tests)
- Fixed 3 ruff errors: removed unused imports (`BodyStateRecord` in `_tools_helpers.py`, `compute_body_state_decay` in test), removed unused variable
- 21 tests pass for body_state_history module
- 1296 total passing, 7 skipped, ruff 0 errors

## TA04: dynamic_temperature WebUI 設定 (2026-07-06)
- `chat.py` HTML テンプレート: Temperatureスライダー直後に「動的温度調整」セクション追加 (toggle + scale slider + top_p slider)
- `chat.js`: applyChatConfig/saveChatConfig に新フィールド3件追加、dynamic_temperature 連動で scale slider の disabled 制御
- `routers/chat.py` の save_chat_config: field_name リストに "dynamic_temperature", "emotion_temperature_scale", "top_p" 追加
- デザイナーが HTML/JS を担当、オーケストレータがルーター修正 + テスト検証
- 1518 passed / 7 skipped / 0 failed, ruff 0 errors

## TA03: dynamic_temperature pipeline 統合 (2026-07-01)
- `InferenceStep.run()` に `effective_temp: float | None = None` パラメータ追加
- オーケストレータ (`ChatService.chat()`) が `config.dynamic_temperature=True` 時のみ `EmotionDrivenSampler.compute()` で実効温度を事前計算
- InferenceStep は PersonaState を直接参照しない — オーケストレータが `turn_ctx.state_raw` から抽出して注入
- `dynamic_temperature=False` 時は `config.temperature` をそのまま使用（後方互換）
- テスト5件追加: effective_temp伝搬、fallback、streamパラメータ確認、sampler計算検証

## プロジェクト概要
Nous: 日本語特化の永続記憶 MCP サーバー。SQLite + Qdrant + Ebbinghaus 忘却曲線。WebUIダッシュボード付き。
3レイヤー構造（L1:MCP拡張, L2:EventBus基盤, L3:OpenCode Plugin）。

## 学習した知識・教訓

### TIME GAP 体験層化（2026-07-01）
- `_generate_time_passage_narrative()` 新規作成: テンプレートベースで時間経過を自然言語化
- 3段階テンプレート: <1h（維持）, 1-24h（body+感情）, >24h（body+話題+感情）
- `_BODY_DECAY_CFG` の config（target / half_life）を直接参照して身体回復を記述
- `_format_lightweight_response` の破壊的変更を避けるため `elapsed_hours=0.0` フォールバック維持
- `emotion_decay_result` を直接受け取って emotion before/after を自然文に統合
- `prepare.py` の時間経過メッセージを英語に変更（T02統一方向に準拠）
- テスト6件追加（short/medium/long/zero/no-emotion/no-body）

### 関数設計ルール: フォールバック（2026-07-01）
- 既存の positional arguments 呼出を壊さないため、新しいキーワード引数は末尾に追加
- `decay_note` (str) は後方互換用に維持し、`elapsed_hours > 0` のときのみ新パスへ
- `_format_state_diff` / `_build_time_comment` は旧パス用に維持

### sandbox_context JSON化責務をラッパー層に統一（2026-06-29）
- `_tool_sandbox_context()` の戻り値を `str`（自前json.dumps）→ `dict` に変更
- MCPラッパー `sandbox_context()` 側で `json.dumps(r, ensure_ascii=False)` するように統一
- `sandbox_files` と同じパターン（core→dict, wrapper→json.dumps）に揃えた
- sandbox無効時・サービス不可時のスケルトン戻り値（pip_packages=[]含むdict）は維持

### sandbox_context pip_packages + auto_emotion（2026-06-29）
- `_tool_sandbox_context()` は常にJSONスケルトンを返す設計。sandbox無効時も空pip_packages含むdictを返し、エラー文字列を返さない
- `session.get_context()` は既に pip3 list --user --format=json をパースして pip_packages を返す（service.py L453-468）
- `_tool_memory_create()` の auto_emotion フラグ: 現状常にTrue。将来 explicit emotion 指定追加時は False 分岐

### ツール設計の統一パターン（継続的）
- MCPツール設計: core関数はdict/構造化データを返し、MCPラッパーでjson.dumpsする
- sandbox_files, sandbox_context がこのパターン準拠済み
- sandbox_execute, sandbox_reset は文字列戻り値（exec結果そのまま）で別扱い

### テスト自動化ルール
- sandboxテスト: `registered_tools` fixtureでMCPラッパー関数を呼び、戻り値は `json.loads()` でパースして検証
- テストは MCPラッパー経由で呼ぶ（コア関数直呼びではない）

### TB05+TB06: ComfyUI ImageGenProvider + healthcheck (2026-07-01)
- `ComfyUIProvider` 新規作成: `nous/infrastructure/image_gen/comfyui.py`
  - `async generate()`: POST /prompt → poll /history → GET /view の fire-and-forget パターン
  - `async health_check()`: GET /system_stats
  - 接続エラー時: 最大2回リトライ（httpx.ConnectError / httpx.TimeoutException）
  - ポーリング: 60回 × 3s = 180s タイムアウト
  - `asyncio.sleep` はテストでモックして高速化
- `ImageGenConfig` に `comfyui_url` フィールド追加
- factory に `"comfyui"` ケース追加
- 注意: httpx 0.28.1 は `Timeout(connect=..., read=...)` 形式をサポートしていない → 全4パラメータ明示が必要
- 12 tests + 1 factory test = 22 total for image_gen module

## プロジェクトの現在の状態
- 全ユニットテスト通過（image_gen: 22 passed）
- pytest-benchmark 未インストール（7 skipped の原因）
- ruff check 0 errors 維持
