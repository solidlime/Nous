# SPEC — Phase 3: UI没入・マルチモーダル

> 出典: `.spec/PLAN.md` (2026-07-26) P3-1 / P3-2 / P3-3 / P3-4
> 最終更新: 2026-07-26（全探索結果反映）

---

## SPEC-3.1: セルフポートレートのオーバービュー表示 (P3-1)

### 現状分析（探索結果: ses_0642a54b7ffeGjZ4UUsW6aXQr9）

**コア発見**: P3-1 は**80% 完了済み**。Overview タブに self-portrait 表示が実装されている。

| 項目 | 状態 | ファイル:行 |
|------|------|------------|
| `image_generate` self_portrait 生成 | ✅ 実装済み | `application/chat/tools/builtin.py:194-345` |
| 画像ファイル保存（`images/self_*.png`） | ✅ 実装済み。`data/persona/{persona}/images/` | `builtin.py:300-301` |
| 画像配信 API | ✅ `GET /api/chat/{persona}/persona/images/{filename}` | `chat_management.py:287-306` |
| Overview ポートレート表示 | ✅ `<div id="overview-portrait">` + JS | `overview-core.js:25-36` |
| dashboard API に `latest_self_portrait` 含む | ✅ glob 最新ファイル | `persona_dashboard.py:174-185` |
| SSE `image_gen_result` 受信時 Overview 自動更新 | **不在** | — |
| 手動「最新ポートレート生成」ボタン | **不在** | — |

### 要件

| # | 要件 | 内容 | 変更ファイル | 規模 |
|---|------|------|-------------|------|
| R1 | SSE 自動更新 | `image_gen_result` SSE 受信 → Overview タブのポートレートを即時差し替え | `static/chat/chat-send.js:530-579`, `features/overview/overview-core.js` | S |
| R2 | 手動生成ボタン | Overview タブに「ポートレートを更新」ボタン。押下で `image_generate(self_portrait=true)` を MCP 経由呼び出し | `features/overview/overview-core.js`, `api/http/sections/overview.py` | M |
| R3 | 生成履歴表示 | 過去の self_portrait 一覧をサムネイルグリッドで表示 | `features/overview/overview-core.js`, `routers/persona/persona_dashboard.py` | M |
| R4 | 設定 UI | config.json の `image_gen_self_portrait_prompt` を Overview から直接編集 | `static/chat/chat-settings.js`, `features/overview/overview-core.js` | S |

### 実装方針
- R1 が最もコスト対効果高い（SSE 受信時の1行追加で済む）
- R2-R4 は任意。Phase 3 の他タスクと並列可能
- 全タスクで `resources/glm-image-srv`（ComfyUI）が稼働している前提

---

## SPEC-3.2: チャット背景・立ち絵 (P3-2)

### 現状分析

| 項目 | 状態 | 備考 |
|------|------|------|
| 背景画像設定 | **不在** | `config.json` にフィールドなし |
| 立ち絵表示 | **不在**（2026-07-18 に旧実装削除） | MEMORY.md:100-103 参照 |
| テーマシステム | ✅ `html.dark` / `html.light` で切替 | `core/theme.js`, `variables.css` |
| グラスモーフィズム | ✅ `.glass` に `backdrop-filter: blur(20px) saturate(180%)` | `theme.css:9-19` |
| 画像アップロードエンドポイント | ✅ `POST /api/chat/{persona}/attachment/upload` | `chat_management.py:247` |

### 要件

| # | 要件 | 内容 | 変更ファイル | 規模 |
|---|------|------|-------------|------|
| R1 | config スキーマ拡張 | `ToolConfig` に `chat_background_url`, `chat_background_dark_url`, `standing_pic_url` 追加 | `domain/tool_config.py` | S |
| R2 | CSS 背景画像 | `#chat-layout` に CSS 変数 `--chat-bg-image` を適用。テーマ別画像切替 | `styles/chat.css`, `styles/variables.css`, `styles/theme.css` | M |
| R3 | 背景設定 UI | チャット設定サイドバーに背景画像 URL 入力＋アップロードボタン | `sections/chat/chat_sidebar_media.py`, `static/chat/chat-settings.js` | M |
| R4 | 立ち絵 DOM 配置 | `#chat-layout` に `<div id="standing-pic">` 追加。CSS で右/左配置 | `sections/chat/chat_layout.py`, `styles/chat.css` | M |
| R5 | アイドルアニメーション | CSS `@keyframes idle-float` でふわふわ揺れ。`will-change: transform` で GPU 合成 | `styles/theme.css` | S |
| R6 | ダッシュボード API 拡張 | `latest_self_portrait` に加え `chat_background_url`, `standing_pic_url` を API レスポンスに含める | `routers/persona/persona_dashboard.py` | S |
| R7 | 感情連動立ち絵（オプショナル） | `emotion` 変化時に対応画像に差し替え（`joy.png`, `sad.png` 等） | `static/chat/chat-send.js`, `static/core/theme.js` | M |

### 制約
- `.glass` の `backdrop-filter` と背景画像の整合性（background-attachment: fixed 推奨）
- テーマ切替時は `html.dark` / `html.light` で CSS 変数をオーバーライド
- 立ち絵は `pointer-events: none` でクリック透過（チャット操作を妨げない）
- 画像は外部 URL またはアップロードの両方に対応（`chat_management.py` の既存エンドポイント流用）

### 実装順序
```
R1 (S: スキーマ) → R2 (M: CSS) → R3 (M: UI) → R6 (S: API) → R4 (M: DOM) → R5 (S: アニメ) → R7 (M: 感情連動・Phase 2後)
```

---

## SPEC-3.3: 音声入力（Speech-to-Text）(P3-3)

### 現状分析（探索結果: ses_0642a1a7affe8RZaEI4zmvgjmD）

**コア発見**: P3-3 は**95% 完了済み**。Web Speech API によるブラウザ内 STT が完全実装されている。

| 項目 | 状態 | ファイル:行 |
|------|------|------------|
| Web Speech API STT | ✅ 完全実装 | `static/chat/chat-voice.js` (71行) |
| マイクボタン UI | ✅ `#chat-voice-btn` 配置済み | `sections/chat/chat_layout.py:51` |
| 認識結果→テキストエリア | ✅ `value = event.results[...]` | `chat-voice.js:37-48` |
| 言語設定 | ✅ `ja-JP` 固定 | `chat-voice.js:30` |
| TTS 出力 | ✅ Irodori 連携完全実装 | `chat-tts.js`, `routers/tts.py` |
| 長文認識 | ❌ `continuous: false` | `chat-voice.js:31` |
| 中間認識表示 | ❌ `interimResults: false` | `chat-voice.js:31` |
| 音声ファイル録音送信 | ❌ 未実装（テキスト認識のみ） | — |

### 要件（機能拡張のみ）

| # | 要件 | 内容 | 変更ファイル | 規模 |
|---|------|------|-------------|------|
| R1 | 長文音声認識 | `continuous: true` に変更。停止ボタンで明示終了 | `static/chat/chat-voice.js:31` | XS |
| R2 | 中間認識表示 | `interimResults: true`。認識途中テキストをリアルタイム表示 | `static/chat/chat-voice.js:31,37-48` | XS |
| R3 | 音声ファイル添付送信 | `MediaRecorder` API で WAV/WebM 録音→既存 `chat-attachments.js` のファイル添付フローに乗せる | `static/chat/chat-voice.js`, `static/chat/chat-attachments.js` | M |
| R4 | 音声入力言語設定 | `persona/config.json` に `voice_input_language` 追加（default `ja-JP`） | `domain/tool_config.py`, `static/chat/chat-settings.js` | S |

### 制約
- Web Speech API は Chrome/Edge/Safari のみ対応。Firefox は非対応
- `continuous: true` 時は `onresult` イベントが蓄積される（50 秒のタイムアウトに注意）
- 音声ファイル添付は Whisper API フォールバックとセットで検討（別タスク化）

---

## SPEC-3.4: 画像入力（マルチモーダルチャット）(P3-4)

### 現状分析（探索結果: ses_0642a1a7affe8RZaEI4zmvgjmD）

**コア発見**: 画像送信パイプラインの **85% は実装済み**。
フロントエンド Base64 変換 → バックエンド受付 → `ChatTurnContext` 伝搬 → `LLMMessage.content_parts` 構築 → OpenAI/Anthropic ネイティブ形式変換まで動作している。

**不足**: LLM プロバイダの vision 能力判定（`supports_vision()`）と非対応モデルへのフォールバック。

### 要件

| # | 要件 | 内容 | 変更ファイル | 規模 |
|---|------|------|-------------|------|
| R1 | `supports_vision()` 追加 | `LLMProvider` 抽象クラスに `supports_vision() -> bool` 追加 | `infrastructure/llm/base.py` | XS |
| R2 | プロバイダ別実装 | Anthropic: `True` / OpenAI: モデル名判定 / Google: `True` / OpenRouter: モデル名に "vision" 含むか | `anthropic.py`, `openai_compat.py`, `google.py` | S |
| R3 | 非 vision フォールバック | `supports_vision()=False` 時に画像をテキスト説明に変換（キャプション用 LLM 呼び出し or ファイル名＋サイズ情報をテキスト注入） | `inference.py:63-76` | M |
| R4 | フォールバック用キャプショナ | vision 非対応時、別途 vision 対応モデルを呼び出して画像説明を生成する `ImageCaptioner` クラス | `infrastructure/llm/image_caption.py`（新規） | M |
| R5 | UI 通知 | vision 非対応時にフロントエンドへ「画像はテキスト説明に変換されます」トースト表示 | `static/chat/chat-send.js`, `static/chat/chat-attachments.js` | S |
| R6 | カメラ撮影（オプショナル） | `MediaDevices.getUserMedia()` でカメラ起動→撮影→添付 | `static/chat/chat-attachments.js` | M |

### 既存で触らないもの（動作確認済み）

| レイヤー | ファイル |
|---------|---------|
| フロントエンド添付 UI | `chat-attachments.js` |
| Base64 変換 | `chat-send.js:301-369` |
| バックエンド受付 | `chat_stream.py:108` |
| ChatTurnContext 伝搬 | `service.py:104` |
| content_parts 構築 | `inference.py:63-76` |
| OpenAI 形式変換 | `openai_compat.py:79-86` |
| Anthropic 形式変換 | `anthropic.py:65-87` |
| 添付アップロード/配信 | `chat_management.py` |

### 実装順序
```
R1 (XS: 抽象メソッド追加) → R2 (S: プロバイダ別実装) → R3+R4 (M: フォールバック) → R5 (S: UI通知) → R6 (M: カメラ・任意)
```

### 制約
- フォールバックのキャプション生成は追加の LLM 呼び出しが発生 → レイテンシに注意
- キャプション生成失敗時は「画像認識は現在のプロバイダでは利用できません」というテキストをユーザー発言に追記するシンプルなフォールバックで十分
- R6（カメラ撮影）は HTTPS 環境必須（`getUserMedia` のセキュリティ要件）

---

## 実装方針（Phase 3 全体）

| 項目 | 方針 |
|------|------|
| 並列度 | P3-1/P3-2/P3-3/P3-4 は**全独立**。4並列実装可能 |
| P3-3 優先度 | **最速完了**。R1+R2 は 2 行変更で完了（XS） |
| P3-4 優先度 | **高**。未完成のマルチモーダルパイプラインを完成させる |
| P3-2 優先度 | **中**。CSS/UI 作業が主。designer（#057）への委譲が適切 |
| 調査 | 本スペック作成時に全探索完了 |
| フロントエンド | CSS 変更・UI コンポーネントは #057 designer に委譲。機械的 JS 変更は #011 fixer |
| テスト | プロバイダ能力判定はユニットテスト、UI はブラウザ手動確認 |
