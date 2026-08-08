# SPEC: tool 孤児メッセージ修正（400エラー対応）

## 背景・問題
- ユーザー環境で `Messages with role 'tool' must be a response to a preceding message with 'tool_calls'` (400) が発生。
- Reasoning ON/OFF 問わず発生（Reasoning は増幅要因）。
- 原因（実データ 96 セッション検証で確定）: 履歴切り詰めのスライスが tool/assistant(tool_calls) のペア構造を壊し、孤児 tool メッセージを生成。現行 48/77 セッションで再現、修正案で 0/77 に解消済み（/tmp/verify_tool_orphan2.py で実証）。

## 修正方針（ユーザー承認済み「両方修正する」）

### F1: 窓広げヘルパー（3箇所に適用）
- `TrimmerMixin` に共通ヘルパー `_adjust_slice_start(messages, start)` を追加:
  - `while start < 0 and messages[start].role == "tool": start -= 1` を返す。
  - スライス後に先頭が tool の場合、1件前に広げて対応する assistant(tool_calls) を含める。
- 適用箇所（全て同型スライス）:
  1. `nous/application/chat/pipeline/trimmer.py:143` — `_truncate_old_messages`: `recent = messages[-keep_count:]` → `recent = messages[_adjust_slice_start(messages, -keep_count):]`。removed_count は len(recent) ベースに修正（広げた分、切り詰め件数が減る）。
  2. `nous/application/chat/service.py:189` — `messages = messages[-max_msgs:]` → `messages = messages[_adjust_slice_start(messages, -max_msgs):]`（TrimmerMixin 継承 or TrimmerMixin._adjust_slice_start 参照）。
  3. `nous/application/chat/pipeline/compress.py:145` — `messages = [summary_msg] + messages[-keep_count:]` → `messages = [summary_msg] + messages[_adjust_slice_start(messages, -keep_count):]`。
- 注意: keep_count/max_msgs が 0 や全件超過の場合は現行動作を維持（スライスしない or そのまま）。
- `_expand_segments` / `session_window.py` は変更しない。

### F2: 非標準 reasoning_content フィールド削除
- `nous/infrastructure/llm/openai_compat.py:102` — `"reasoning_content": ""` を assistant(tool_calls) メッセージから削除。
- 背景: OpenAI 仕様に無いフィールドで、Console Go プロキシ翻訳でメッセージ破棄リスク。応答側の delta.reasoning_content 処理は変更しない。

### T: テスト
1. `tests/unit/test_compress_step.py`（または該当テストファイル）: `_truncate_old_messages` で (a) 末尾スライス先頭が tool のケースで assistant(tool_calls) が含まれる (b) 通常ケースで従来通り (c) keep_recent_turns=0 で無変更。
2. `tests/unit/test_llm_reasoning.py`: `_to_api_messages` の assistant(tool_calls) メッセージに `reasoning_content` が含まれないことを確認。

## 検証
- pytest（システム python3 = rtk pytest。.venv には openai/anthropic が無いため使用禁止）
- 実データ再現スクリプト（/tmp/verify_tool_orphan2.py 相当）で孤児 0 を再確認
- ruff / py_compile

## 非対象
- DB マイグレーション・既存履歴の修正は不要（切り詰めは毎ターン走るため自然解消）
- CoT 実装の未コミット変更（base.py/events.py/inference.py 等）とは別ファイル（service.py のみ共有だがコンフリクト注意 — CoT は service.py 未変更のため安全）
