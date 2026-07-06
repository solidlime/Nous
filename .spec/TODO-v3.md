# TODO v3 — SillyTavern採用 + Dynamic Temperature + ペルソナ可視化 + 音声

## Phase A: Dynamic Temperature (P0)

### TA01: EmotionDrivenSampler ドメイン層 [小] ✅
- [x] TA01a: `nous/domain/sampling.py` 新設 — `EmotionDrivenSampler.compute(base_temp, emotion, intensity) -> float`
- [x] TA01b: 感情別モディファイア辞書 + intensity スケール + clamp [0.1, 1.8]
- [x] TA01c: ユニットテスト (全感情カバー, edge: intensity=0, intensity=1)
- **依存**: なし
- **担当**: @fixer

### TA02: ChatConfig 拡張 [極小] ✅
- [x] TA02a: `nous/domain/chat_config.py` に `dynamic_temperature: bool = True`, `emotion_temperature_scale: float = 0.2`, `top_p: float | None = None` 追加
- [x] TA02b: DB マイグレーション (v032_dynamic_temp) — ALTER TABLE chat_settings
- [x] TA02c: `LLMProvider.stream()` に top_p パラメータ追加 → Anthropic/OpenAI provider に伝搬
- [x] TA02d: テスト更新
- **依存**: なし (TA01 と並列可)
- **担当**: @fixer

### TA03: Pipeline orchestrator 修正 [小] ✅
- [x] TA03a: `nous/application/chat/service.py` — パイプラインオーケストレータが `turn_ctx.state_raw` から感情取得 → `EmotionDrivenSampler.compute()` → `effective_temp` を `InferenceStep` に注入
- [x] TA03b: `InferenceStep` が `effective_temp` パラメータを受け取り、`provider.stream()` に渡すよう修正
- [x] TA03c: 統合テスト — `TestDynamicTemperatureInference` 5件 (effective_temp差、fallback、stream伝搬、sampler統合)
- **依存**: TA01, TA02
- **担当**: @fixer (設計レビュー: @oracle)

### TA04: WebUI 設定追加 [極小] ✅
- [x] TA04a: `nous/api/http/static/chat.js` + `nous/api/http/sections/chat.py` — Chat 設定パネルに Dynamic Temperature toggle + scale slider + top_p slider
- [x] TA04b: `nous/api/http/routers/chat.py` — 設定保存エンドポイントに新フィールド追加
- [x] TA04c: 動作確認 (ruff check 通過, 関連テスト133件通過)
- **依存**: TA01-TA03
- **担当**: @designer

---

## Phase B: 動的ペルソナ画像生成 (P0-P1)

### TB00: PortraitGenerationConfig [小] ← クリティカル前提
- [ ] TB00a: `nous/config/settings.py` に `PortraitGenerationConfig` 追加
  - enabled: bool = False (**デフォルトOFF**)
  - provider: "comfyui" | "openai" | "stability" = "comfyui"
  - comfyui_url: str = "http://comfyui:8188"
  - auto_generate: bool = False
  - generate_interval_min: int = 10
  - size: str = "512x512"
  - quality: str = "standard"
  - emotion_threshold: float = 0.3
  - max_monthly_budget: float = 5.0
- [ ] TB00b: `ChatConfig` に `portrait_gen: PortraitGenerationConfig` 追加 (image_gen_* と分離)
- [ ] TB00c: テスト
- **依存**: なし
- **担当**: @fixer

### TB01: ペルソナ外見記述フィールド [小]
- [ ] TB01a: `PersonaState` に `appearance: str | None` 追加
- [ ] TB01b: `persona_info` dict の `appearance` キーから自動読み込み
- [ ] TB01c: `nous_item` の装備品に `visual_desc: str | None` 追加 (衣装記述用)
- [ ] TB01d: DB マイグレーション
- [ ] TB01e: テスト
- **依存**: なし (TB00 と並列可)
- **担当**: @fixer

### TB02: PortraitPromptBuilder [中] ✅
- [x] TB02a: `nous/domain/persona/portrait_prompt.py` 新設
- [x] TB02b: **2モード合成**: (1) LLM合成: scene + persona外見 = 完全プロンプト (2) 自動合成: emotion/bodyのみ
- [x] TB02c: 入力: persona, scene (LLM指定, optional), emotion, intensity, body_state, equipment
- [x] TB02d: 出力: Animagine XL 4.0 プロンプト文字列 + negative_prompt
- [x] TB02e: 感情→形容詞マッピング (joy="smiling", anger="glaring", 等)
- [x] TB02f: ユニットテスト (sceneあり/なし, 全感情, 装備あり/なし, 外見未設定)
- **依存**: TB01
- **担当**: @fixer

### TB03: PortraitGenerationService [中]
- [ ] TB03a: `nous/application/portrait/service.py` 新設
- [ ] TB03b: **LLM-driven**: MCPツールから呼ばれ `PromptBuilder(scene=llm_scene)` → ComfyUI → 画像返却
- [ ] TB03c: **Auto-generate**: 背景自動生成 (デフォルトOFF, emotion_threshold, interval_min)
- [ ] TB03d: レート制限 + プロンプトhashキャッシュ (TTL 5分)
- [ ] TB03e: 生成失敗時のフォールバック (感情カラーアイコン)
- [ ] TB03f: 月額予算管理 (generate_count カウンタ)
- [ ] TB03g: テスト
- **依存**: TB00, TB02, TB05 (ComfyUI provider)
- **担当**: @fixer

### TB04: MCP ツール `persona_portrait` (LLM-driven 核) 🆕
- [ ] TB04a: `nous/api/mcp/tools/portrait.py` 新設 — `persona_portrait(scene, style?)` ツール
- [ ] TB04b: `nous/application/chat/tools/definitions.py` に tool definition 追加
- [ ] TB04c: LLMが scene を指定 → `PortraitPromptBuilder` でペルソナ情報自動注入 → ComfyUI
- [ ] TB04d: 戻り値: base64 画像 + revised_prompt
- [ ] TB04e: 統合テスト (LLM scene合成, フォールバック)
- **依存**: TB02, TB03
- **担当**: @fixer

### TB05: ComfyUI ImageGenProvider [中]
- [ ] TB05a: `nous/infrastructure/image_gen/comfyui.py` 新設
- [ ] TB05b: `comfy-api-simplified` 依存追加
- [ ] TB05c: ワークフロー JSON テンプレート (`models/persona_portrait.json`)
- [ ] TB05d: Animagine XL 4.0 プロンプトパラメータ設定 (30 steps, Euler Ancestral, CFG 5.0, 512x512)
- [ ] TB05e: ヘルスチェック + タイムアウト + リトライ
- [ ] TB05f: `factory.py` に comfyui provider 追加
- [ ] TB05g: テスト
- **依存**: なし (TB00-TB02 と並列可)
- **担当**: @fixer

### TB06: ComfyUI 接続設定 [小]
- [ ] TB06a: `PortraitGenerationConfig.comfyui_url` で外部 ComfyUI を指定（デフォルト `http://localhost:8188`）
- [ ] TB06b: healthcheck `/system_stats` 死活監視
- [ ] TB06c: 非起動時のフォールバック (感情アイコン)
- [ ] TB06d: `.env.example` に `COMFYUI_URL` 追記
- **依存**: なし
- **担当**: @fixer

### TB07: WebUI ペルソナ画像表示 [中]
- [ ] TB07a: Overview タブ: 最新生成画像 + 「Generate Now」ボタン (scene 入力可)
- [ ] TB07b: チャットタブ: 右サイドバー上段に最新画像表示
- [ ] TB07c: 生成中ローディング表示 (skeleton + pulse)
- [ ] TB07d: フォールバック: 既存の感情カラーアイコン
- [ ] TB07e: `portrait.js` 新規JSファイル (SSE ハンドラ)
- [ ] TB07f: 自動生成設定パネル (interval, threshold, enabled)
- **依存**: TB02, TB03, TB05
- **担当**: @designer

### TB08: SSE イベント [小]
- [ ] TB08a: `nous/api/http/routers/events.py` — `portrait.generate_start/complete/error` イベント追加
- [ ] TB08b: EventBus 連携
- [ ] TB08c: フロントエンド SSE ハンドラ
- **依存**: TB03
- **担当**: @fixer

---

## Phase C: WebUI リアルタイム化 (P2)

### TC01: SSE イベント拡張 [小]
- [ ] TC01a: `PersonaService.update_emotion()` → `emotion_change` イベント発行
- [ ] TC01b: `PersonaService.update_physical_state()` → `body_state_change` イベント発行
- [ ] TC01c: `events.py` に `emotion_change`, `body_state_change` 追加
- **依存**: なし (TB08 と並列可)
- **担当**: @fixer

### TC02: フロントエンドリアルタイム更新 [小]
- [ ] TC02a: `base.js` EventSource ハンドラ: emotion_change → 感情バー更新
- [ ] TC02b: body_state_change → 身体バー更新
- [ ] TC02c: portrait.updated → ペルソナ画像更新
- **依存**: TC01, TB08 (SSE events)
- **担当**: @designer

---

## Phase D: SillyTavern 選択採用 (P2-P3)

### TD01: Author's Note 常時注入 [小]
- [ ] TD01a: `PersonaState` に `author_note: str | None` 追加
- [ ] TD01b: System prompt 末尾に注入ロジック (before messages)
- [ ] TD01c: Frequency 制御: "always" | "every_n" | "on_emotion_change"
- [ ] TD01d: テスト
- **依存**: なし
- **担当**: @fixer

### TD02: ペルソナ PNG メタデータ埋め込み [中]
- [ ] TD02a: `nous/infrastructure/persona_card.py` 新設 (PNG tEXt ccv3 チャンク読み書き)
- [ ] TD02b: import/export MCP ツール (`persona_export_card`, `persona_import_card`)
- [ ] TD02c: WebUI Import/Export タブに「Download Persona Card」ボタン
- [ ] TD02d: テスト (round-trip)
- **依存**: TB01, TB02 (外見情報が必要)
- **担当**: @fixer

---

## Phase E: Voice AI (P2-P3, 独立)

### TE01: Irodori-TTS 接続設定 [小]
- [ ] TE01a: `IrodoriConfig` 設定モデル追加 (`irodori_url`, `enabled`)
- [ ] TE01b: `.env.example` に `IRODORI_TTS_URL` 追記
- [ ] TE01c: ヘルスチェック + 非起動時フォールバック
- [ ] TE01d: **注**: Irodori-TTS は GPU 必須 (CPU では実用不可)。別 PC or GPU サーバーで稼働前提
- **依存**: なし
- **担当**: @fixer

### TE02: VoiceEngine 抽象 + Irodori 実装 + 感情変換 [中]
- [x] TE02a: `nous/infrastructure/voice/base.py` — VoiceEngine ABC
- [x] TE02b: `nous/infrastructure/voice/irodori.py` — OpenAI SDK で `/v1/audio/speech`
- [x] TE02c: `nous/infrastructure/voice/emotion.py` — **`build_caption(persona) → str`**: context_note + 口調 + 感情 を自然言語 caption に変換。固定マッピングではなくコンテキスト駆動
- [x] TE02d: テキストへの絵文字注入 (joy→😊, anger→😠, 等)
- [x] TE02e: `nous/infrastructure/voice/factory.py`
- [ ] TE02f: 漢字→ひらがな前処理 (`pyopenjtalk` 依存追加) ← スキップ (TE02)
- [ ] TE02g: チャンク分割 (100文字区切り) ← スキップ (TE02)
- [x] TE02h: テスト (26 tests)
- **依存**: TE01
- **担当**: @fixer

### TE03: MCP ツール [小]
- [ ] TE03a: `nous/api/mcp/tools/tts.py` — `irodori_tts`, `irodori_voices`, `irodori_register_voice`
- [ ] TE03b: `nous/application/chat/tools/definitions.py` に tool definition 追加
- [ ] TE03c: `nous/application/chat/tools/builtin.py` にハンドラ追加
- **依存**: TE02
- **担当**: @fixer

### TE04: WebUI 設定・再生 [中]
- [ ] TE04a: Chat 設定パネル「Voice」セクション追加
- [ ] TE04b: チャットメッセージ横の 🎵 再生ボタン
- [ ] TE04c: 自動再生モード (レスポンス受信完了後)
- [ ] TE04d: TTS テスト再生ボタン
- **依存**: TE02, TE03
- **担当**: @designer

---

## Phase F: アイテム衣装連携 (P3)

### TF01: 装備品プロンプト連携 [小]
- [ ] TF01a: `PortraitPromptBuilder` が `nous_item` 装備情報を衣装記述に変換
- [ ] TF01b: `equipment_desc` = "wearing {top_desc}, {outer_desc}, {acc_desc}"
- [ ] TF01c: テスト
- **依存**: TB01 (visual_desc), TB02
- **担当**: @fixer

---

## ドキュメント

### TDOC: ドキュメント更新
- [ ] TDOCa: `docs/llm_usage_guide.md` — 新ツール (DynaTemp, portrait, voice) 追加
- [ ] TDOCb: `README.md` — Phase A-E の概要追加
- [ ] TDOCc: プロポーザル `docs/research/` に調査結果アーカイブ
- **依存**: 全 Phase 完了後
- **担当**: @fixer

---

## 実行順序

```
Group 1 (即時):  [TA01, TA02] + [TB00, TB01] + [TD01, TE01] → 5並列
Group 2:        [TA03] + [TB02, TB05, TB06] → 3並列 (TA03 は TA01-TA02 待ち)
Group 3:        [TB03, TB04, TB07] + [TA04] → 4並列 (TB03 は TB02, TB05 待ち, TB04 は TB03 待ち)
Group 4:        [TB08] + [TC01] → 2並列 → [TC02]
Group 5:        [TD02] → 単独
Group 6:        [TE02] → [TE03] → [TE04] → 直列 (voice)
Group 7:        [TF01] → 単独 (TB01, TB02 待ち)
Group Final:    [TDOC] → 単独
```

## 検証ゲート
各 Group 完了後:
1. `python -m pytest tests/ -x --tb=short` → 全テスト通過
2. `ruff check .` → 0 errors
3. `git commit && git push` → GitHub Actions パス
