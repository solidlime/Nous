# SPEC — CoT（思考過程）表示 + 履歴保存（TTS 除外）

> 出典: ユーザー要望 (2026-08-08)「一応ほしいな。ただ読み上げからは除外してほしい」
> 追加確認: 履歴にも保存する（表示専用ではない）
> 調査: exp-2（TTS 経路 / SSE 構造 / 履歴保存）、orchestrator 追確認（segments 復元経路）

## 背景

Thinking トグル実装（SPEC-thinking-toggle.md、完了）により reasoning が有効化されるが、
現在は思考過程（CoT）がプロバイダ実装内で捨てられ、最終回答のみ表示される。
ユーザー要望: CoT を表示したい。ただし **TTS 読み上げからは除外**。**履歴にも保存**する。

### 調査結果（exp-2）

**TTS 経路（フロント2系統のみ。バックエンド tts.py は受け取った text を読むだけ・フィルタ機能なし）:**

| 経路 | 発火点 | 収集対象 |
|---|---|---|
| 自動再生 | chat-send.js:572-575 → `N.Chat.tts.autoPlay` | contentParts の `type === "text"` のみ（:556-570） |
| 手動ボタン | chat-send.js:190-195 / :83-93 → `N.Chat.tts.play` | `div.querySelectorAll(".chat-bubble")` の全テキスト |

→ **構造的除外の2必須ルール**: (1) CoT を `TextDeltaEvent`/`text_delta` に混ぜない（専用イベントにする）
(2) CoT 表示 DOM に `.chat-bubble` クラスを付けない（専用クラス `.chat-thinking-bubble` にする）

**SSE 拡張点**: events.py に新イベントクラス追加 → base.py の ChatEvent ユニオン → プロバイダで
`reasoning_content`（OpenAI）/ `thinking_delta`（Anthropic）を拾って yield → inference.py で SSE 変換
→ chat-send.js の分岐追加。SSE 送出ループ: service.py:221-224（イベントはそのまま流れる）。

**履歴保存**: service.py:228-229 は `TextDeltaSSE` のみ `full_response` に蓄積 → thinking を別イベントに
すれば混入しない。`session.add(..., segments=turn_ctx.segments)`（service.py:233-239）で segments を保存。
segments に `{"type": "thinking", "content": "..."}` を追加すれば DB に保存される
（SQLite chat_sessions の messages JSON 内、スキーマ変更不要）。`_expand_segments`
（session_window.py:49-79）は未知 type を黙って無視 → 次ターンプロンプトには混ざらない（望ましい挙動）。

**履歴復元**: chat-history.js の `_appendSegmentsToBubble`（:98-209）が segments を要素描画。
`seg.type === "text"` / `"tool_call"` / `"tool_result"` の分岐がある → `"thinking"` 分岐を追加すれば
履歴復元時に CoT 表示可能。履歴復元は segments ありなら `appendChatMessage(role, "", ...)` +
`_appendSegmentsToBubble` の流れ（chat-history.js:285-289, :525-526）。

## 要件

| # | 要件 | 内容 |
|---|------|------|
| R1 | イベント型 | `base.py` の ChatEvent ユニオンに `ThinkingDeltaEvent`（content: str）を追加 |
| R2 | SSE イベント | `events.py` に `ThinkingDeltaSSE`（type: `"thinking_delta"`, content）を追加。`_sse_encode` で配信 |
| R3 | OpenAI 拾い上げ | `openai_compat.py` ストリーム処理で `delta.reasoning_content` を拾い、チャンクごとに `ThinkingDeltaEvent` を yield（現状 :195-197 は content のみ処理） |
| R4 | Anthropic 拾い上げ | `anthropic.py` で `delta.type == "thinking_delta"` を拾い `ThinkingDeltaEvent` を yield（現状 :155-161 は text のみ処理） |
| R5 | パイプライン | `inference.py` のイベントループに `ThinkingDeltaEvent` 分岐追加: `ThinkingDeltaSSE` を yield + `_thinking_text` に蓄積。tool_call フラッシュ・Done/ループ終了時に `{"type": "thinking", "content": ...}` を `turn_ctx.segments` に追加（text セグメントと同じパターン）。`service.py` は変更不要（segments は自動保存、full_response には混入しない） |
| R6 | フロント: ストリーミング表示 | `chat-send.js` SSE ループ（:465 付近）に `thinking_delta` 分岐追加。専用クラス `.chat-thinking-bubble` の `<details>` 折りたたみブロックを assistant div に追加（デフォルト開、サマリ「思考過程」）。**contentParts には push しない**（TTS 自動再生・コピー対象から除外） |
| R7 | フロント: 履歴復元 | `chat-history.js` の `_appendSegmentsToBubble`（:98-209）に `seg.type === "thinking"` 分岐追加。同様の `.chat-thinking-bubble` `<details>` として復元描画 |
| R8 | CSS | `chat.css` に `.chat-thinking-bubble` スタイル追加（tool_call と区別できる薄い背景・イタリック等。折りたたみは `<details>` 標準） |
| R9 | TTS 除外の保証 | 上記ルール (1)(2) をテストで検証: reasoning テキストが `text_delta` / `done` の allText（contentParts text のみ）に含まれないこと、手動 TTS 収集セレクタ `.chat-bubble` が `.chat-thinking-bubble` を含まないこと（DOM クラス検証） |
| R10 | テスト | (a) OpenAICompatProvider: reasoning_content が ThinkingDeltaEvent として yield され text と分離される (b) Anthropic: thinking_delta 同様 (c) inference: ThinkingDeltaSSE yield + segments に type:"thinking" が保存される (d) service: thinking が full_response / DB 保存 assistant テキストに混入しない (e) フロント JS: node --check |
| R11 | ドキュメント | `docs/llm_usage_guide.md` に SSE イベント `thinking_delta` を追記（イベント一覧がある場合）。MCP ツール変更なし → 該当セクションのみ |

### 制約
- **TTS 除外は構造的保証**: `.chat-bubble` クラスを絶対に使わない。`contentParts` に thinking を push しない
- **保存対象は segments のみ**: DB スキーマ・マイグレーション・`from_db`・履歴 API は全て無変更
- **次ターンプロンプトに混ぜない**: `_expand_segments` の未知 type 無視を利用（session_window.py は変更しない）
- thinking テキストが空の場合は segment を追加しない
- 既存の text/tool_call/tool_result セグメントの挙動は不変

## 検証要件

| # | 項目 | 方法 |
|---|------|------|
| V1 | 単体テスト | 新規/追記テストを実行: `pytest tests/unit/test_llm_reasoning.py tests/unit/test_chat_pipeline.py tests/unit/test_chat_service.py -q`（システム python3。.venv には openai/anthropic が無いため） |
| V2 | 回帰 | 変更モジュールに直接依存するテストのみ個別実行（フルスイート禁止: メモリ不足） |
| V3 | lint | `ruff check` 対象ファイル PASS |
| V4 | 型チェック | `py_compile` / node --check |
| V5 | UI 確認 | ブラウザ実機確認（puppeteer MCP、http://100.112.180.92:26262/）: ①reasoning ON で送信 → thinking_delta 受信・.chat-thinking-bubble 表示 ②TTS 手動再生時に思考テキストが読まれない ③履歴復元（リロード）で CoT 表示 ④DB segments に thinking が保存されている（sqlite 確認） |

## 実装方針
- バックエンド（events.py / base.py / openai_compat.py / anthropic.py / inference.py + テスト）と
  フロントエンド（chat-send.js / chat-history.js / chat.css）は独立 → **並列 fixer**
- 契約: SSE イベント名 `thinking_delta`、segment type `"thinking"`、DOM クラス `.chat-thinking-bubble` を固定
- UI は既存 tool_call `<details>` パターンの踏襲（#057 介入不要。視覚的質感は既存パターンで統一）
- コミット: バックエンド / フロント / docs の分割
