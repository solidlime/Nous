# TODO v4 — 画像生成 (ComfyUI) + 音声出力 (Irodori) + チャット同期

## ✅ 完了済み

### Phase A: Dynamic Temperature (P0)
| タスク | 内容 | コミット |
|--------|------|----------|
| TA01 | `EmotionDrivenSampler` — 感情駆動温度計算 | 3516e2a 他 |
| TA02 | `ChatConfig` 拡張 — `dynamic_temperature`, `emotion_temperature_scale`, `top_p` | 3516e2a 他 |
| TA03 | Pipeline orchestrator 修正 — ChatService → InferenceStep | 135a236 |
| TA04 | WebUI 設定パネル — toggle + scale slider + top_p | 7adf717 |

---

## Phase X: チャットログ同期修正 (P0) 🆕

**問題**: `session_id` が `localStorage` 管理 → PC/スマフォで別セッションに。チャットログが一致しない。

### CX01: session_id 固定化 [極小]
- [ ] CX01a: `chat.js` の `getChatSessionId()` → localStorage の代わりに固定 `"main"` を返す
- [ ] CX01b: `clearChatHistory()` 時にDBレコードのDELETEも行う（orphan防止）
- [ ] CX01c: `restoreChatHistory()` が固定session_idで動作することの確認
- **依存**: なし
- **担当**: @fixer

---

## Phase B: ペルソナ画像生成 (ComfyUI連携) (P0-P1)

**現状**: ドメイン層 (PromptBuilder) + インフラ層 (ComfyUIProvider) は実装済み。Configも存在。
**残り**: アプリケーションサービス層 + MCPツール + WebUI + SSE

### ✅ TB02: PortraitPromptBuilder [済]
- `nous/domain/persona/portrait_prompt.py` — 2モード (LLM scene / auto)、感情マッピング

### ✅ TB05: ComfyUIProvider [済]
- `nous/infrastructure/image_gen/comfyui.py` — fire-and-forget + ポーリング、リトライ、factory連携

### TB01: ペルソナ外見記述フィールド [小]
- [ ] `PersonaState` に `appearance: str | None` 追加
- [ ] `persona_info` dict の `appearance` キーから自動読み込み
- [ ] DB マイグレーション + テスト
- **依存**: なし
- **担当**: @fixer

### TB03: PortraitGenerationService [中]
- [ ] `nous/application/portrait/service.py` 新設
- [ ] `generate(scene?)` → PromptBuilder → ComfyUI → base64画像
- [ ] レート制限 + プロンプトhashキャッシュ (TTL 5分)
- [ ] 生成失敗時のフォールバック (感情カラーアイコン)
- [ ] テスト
- **依存**: TB01, TB02, TB05
- **担当**: @fixer

### TB04: MCP ツール `persona_portrait` [小]
- [ ] `nous/api/mcp/tools/portrait.py` 新設
- [ ] tool definition + ハンドラ追加
- [ ] 統合テスト
- **依存**: TB03
- **担当**: @fixer

### TB06: ComfyUI 接続設定の残り [極小]
- [ ] `.env.example` に `COMFYUI_URL` 追記
- [ ] 非起動時フォールバック確認
- **依存**: TB05
- **担当**: @fixer

### TB07: WebUI ペルソナ画像表示 [中]
- [ ] Overview タブ: 最新生成画像 + 「Generate Now」ボタン
- [ ] チャットタブ: サイドバー上段に最新画像表示
- [ ] 生成中ローディング (skeleton + pulse)
- [ ] 自動生成設定パネル
- **依存**: TB03, TB05
- **担当**: @designer

### TB08: SSE ポートレートイベント [小]
- [ ] `events.py` に `portrait.generate_start/complete/error` 追加
- [ ] EventBus 連携
- [ ] フロントエンド SSE ハンドラ
- **依存**: TB03
- **担当**: @fixer

---

## Phase E: 音声出力 (Irodori-TTS連携) (P1-P2)

**現状**: `IrodoriConfig` は settings.py に存在。コードはゼロ。
**残り**: 全タスク（インフラ → MCP → WebUI）

### TE01: Irodori-TTS 設定の残り [極小]
- [ ] `.env.example` に `IRODORI_TTS_URL` 追記
- [ ] ヘルスチェック確認
- **依存**: なし
- **担当**: @fixer

### TE02: VoiceEngine 抽象 + Irodori 実装 [中]
- [ ] `nous/infrastructure/voice/base.py` — VoiceEngine ABC (`synthesize(text, emotion) → bytes`)
- [ ] `nous/infrastructure/voice/irodori.py` — OpenAI SDK `/v1/audio/speech` 実装
- [ ] `nous/infrastructure/voice/emotion.py` — `build_caption(persona) → str` (context_note + 口調 + 感情)
- [ ] テキスト絵文字注入 (joy→😊, anger→😠)
- [ ] `nous/infrastructure/voice/factory.py`
- [ ] 漢字→ひらがな前処理 + チャンク分割 (100文字)
- [ ] テスト
- **依存**: TE01
- **担当**: @fixer

### TE03: MCP ツール `irodori_tts` [小]
- [ ] `nous/api/mcp/tools/tts.py` 新設
- [ ] tool definition + ハンドラ追加
- [ ] 統合テスト
- **依存**: TE02
- **担当**: @fixer

### TE04: WebUI 音声設定・再生 [中]
- [ ] Chat 設定パネル「Voice」セクション
- [ ] チャットメッセージ横の 🎵 再生ボタン (base64/wav)
- [ ] 自動再生モード
- **依存**: TE02, TE03
- **担当**: @designer

---

## 延期 (将来対応)

| Phase | 内容 | 理由 |
|-------|------|------|
| Phase C | WebUI リアルタイム化 (SSE emotion/body) | 画像・音声完了後に着手 |
| Phase D | SillyTavern 連携 (Author's Note, ペルソナカード) | 後回し |
| Phase F | アイテム衣装連携 | TB01 完了後に価値が出る |
| TDOC | ドキュメント更新 | 全Phase完了後 |

---

## 実行順序

```
Group 0 (即時): CX01 [chat sync fix] → 単独・最優先

Group 1 (並列): 
  Image lane:  TB01 [外見フィールド] + TB06 [.env 残り]
  Voice lane:  TE01 [.env 残り]
  → 3並列 (依存なし)

Group 2 (並列):
  Image:        TB03 [PortraitGenerationService]
  Voice:        TE02 [VoiceEngine + Irodori]
  → 2並列 (Group 1 待ち)

Group 3 (並列):
  Image:        TB04 [MCPツール] + TB08 [SSE]
  Voice:        TE03 [MCPツール]
  → 3並列 (Group 2 待ち)

Group 4 (デザイン):
  Image:        TB07 [WebUI 画像表示]
  Voice:        TE04 [WebUI 音声再生]
  → 2並列 (Group 3 待ち、両方 @designer)
```

## 検証ゲート
各 Group 完了後:
1. `python3 -m pytest tests/ --ignore=tests/benchmark --ignore=tests/integration/test_dashboard_e2e.py -q` → 全テスト通過
2. `ruff check .` → 0 errors
3. `git commit && git push` → GitHub Actions パス
