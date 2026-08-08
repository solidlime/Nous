# TODO — Phase 1: 検証・即時改善 (2026-07-26)

> SPEC: `.spec/SPEC.md` / PLAN: `.spec/PLAN.md` P1-1, P1-2
> 注意: フルテストスイートはメモリ不足のリスクあり。テストは対象ファイル指定で実行すること。

## P1-1: 記憶減衰・想起スコアの動作検証 ✅ 完了
- [x] 1.1 DecayWorker デバッグログ追加 → `30a3fbd`
- [x] 1.2 オーファン memory_strength クリーンアップ migration v4 → `ac71ee2`
- [x] 1.3 strength_repo FK エラーログのサマリー集計化 → `2fdafdf`
- [x] 1.4 減衰スコアが検索結果に反映されることの統合テスト追加 → `8c6a71a`

## P1-2: 応答検証の動作確認 ✅ 完了
- [x] 2.1 PostProcessStep validation gaps ドキュメント化 → `65dd07e`
- [x] 2.2 キャラクター矛盾検出能力のギャップテスト作成 → `65dd07e`
- [x] 2.3 ルールベース後処理検証パス（response_validator.py）追加 → `a0f78f7` `65dd07e`

## 検証
- [x] V1: `pytest tests/unit/test_decay_worker.py tests/unit/test_memory_strength.py tests/unit/test_rankers.py tests/integration/test_decay_search.py -x -q` → 34 passed
- [x] V2: `pytest tests/unit/test_response_validator.py tests/unit/test_post_process_validation.py -x -q -v` → 19 passed
- [x] V4: `ruff check` → 12 pre-existing（新規 issue なし）
- [x] V5: migration v4 冪等性 → 2回目実行で 0件削除・成功確認

## 実装サマリー

| コミット | 内容 | フェーズ |
|----------|------|---------|
| `30a3fbd` | DecayWorker ログ追加 | P1-1 |
| `ac71ee2` | Migration v4（orphan cleanup） | P1-1 |
| `2fdafdf` | strength_repo FK エラー改善 | P1-1 |
| `8c6a71a` | 減衰×検索 統合テスト | P1-1 |
| `a0f78f7` | response_validator.py（新規） | P1-2 |
| `f627c5d` | test_response_validator.py | P1-2 |
| `65dd07e` | post.py 統合 + gap テスト | P1-2 |

---

## 次フェーズ（Phase 2〜5）

> 詳細 SPEC: `.spec/SPEC-PHASE2.md` `.spec/SPEC-PHASE3.md` `.spec/SPEC-PHASE4.md` `.spec/SPEC-PHASE5.md`

### Phase 2 優先実装タスク（計画承認後）
- [ ] P2-1 R4: `kind='chat'` デッドコード削除（XS）
- [ ] P2-1 R1+R2: SearchQuery kind フィルタ + MCP 公開（S、並列可）
- [ ] P2-1 R5: `_smart_search` kind 伝搬修正（XS）
- [ ] P2-2a R1+R2: 減衰パラメータ config 化（S）
- [ ] P2-2a R3+R4: emotion_history migration v5 + persona カラム（M）
- [ ] P2-1 R3: auto-capture kind 推論（M）
- [ ] P2-2a R5: WebUI 減衰設定追加（S）
- [ ] P2-2a R6: 感情推移グラフ（Overview）（M）

### Phase 3 優先実装タスク（P2 と並列可）
- [ ] P3-3 R1+R2: 長文音声認識 + 中間表示（XS、最速完了）
- [ ] P3-4 R1+R2: `supports_vision()` 追加 + プロバイダ実装（S）
- [ ] P3-4 R3+R4: 非 vision フォールバック + ImageCaptioner（M）
- [ ] P3-1 R1: SSE 自動更新ポートレート（S）
- [ ] P3-2 R1: config スキーマ拡張（S）
- [ ] P3-2 R2+R3: CSS 背景画像 + 設定 UI（M → #057 designer）
- [ ] P3-2 R4+R5+R6: 立ち絵 DOM + アニメ + API（M → #057 designer）

---

## Thinking トグル + effort 設定（2026-08-08）✅ 完了

> SPEC: `.spec/SPEC-thinking-toggle.md`。要望: チャット LLM の thinking on/off トグル + ヴァリアント（effort）スライダー

- [x] R1: ProviderConfig に `reasoning_enabled` / `reasoning_effort` 追加（バリデータ付き）
- [x] R2: `stream()` に `reasoning_effort` 引数追加（後方互換: 既定 None）
- [x] R3: OpenAICompatProvider — OpenRouter は `reasoning:{effort}`、他は `reasoning_effort` 送信
- [x] R4: AnthropicProvider — effort→budget_tokens（low=2048/medium=4096/high=8192/max=16384）で `thinking` 有効化
- [x] R6: inference.py から config 値伝播
- [x] R7: 設定パネルに「思考モード（Reasoning）」チェックボックス + 4 段階スライダー（OFF 時 disabled）
- [x] R8: chat-settings.js apply/save 対応（ChatConfig Facade がフラット自動保存）
- [x] R9: テスト追加（test_provider_config.py / test_llm_reasoning.py 新規 + 既存追記）

### 検証
- [x] V1/V2: 新規 17 passed。既存 158 passed / 12 failed（全て既存起因、stash 比較で確認済み）
- [x] V3: ruff 対象ファイル All checks passed
- [x] V5: ブラウザ実機確認（puppeteer）: トグル ON/OFF・スライダー disabled 制御・ラベル同期（low/high/max）・保存→API 反映（true/high）・リロード復元 すべて確認

### コミット
| コミット | 内容 |
|----------|------|
| `1b366af` | feat(llm): reasoning_effort バックエンド実装 + テスト |
| `b575067` | feat(ui): 思考モードトグル + effort スライダー |
| `19d5a8b` | docs: llm_usage_guide に Reasoning セクション追加 |

---

## CoT 表示 + 履歴保存（2026-08-08）

> SPEC: `.spec/SPEC-cot-display.md`。要望: CoT 表示（TTS 読み上げ除外・履歴保存あり）

- [ ] R1: base.py に ThinkingDeltaEvent 追加
- [ ] R2: events.py に ThinkingDeltaSSE（type: "thinking_delta"）追加
- [ ] R3: OpenAICompatProvider で delta.reasoning_content 拾い上げ
- [ ] R4: AnthropicProvider で thinking_delta 拾い上げ
- [ ] R5: inference.py 分岐（ThinkingDeltaSSE yield + segments に type:"thinking" 保存）
- [ ] R6: chat-send.js に thinking_delta 分岐（.chat-thinking-bubble 折りたたみ表示）
- [ ] R7: chat-history.js _appendSegmentsToBubble に thinking 復元分岐
- [ ] R8: chat.css に .chat-thinking-bubble スタイル
- [ ] R9: TTS 除外の構造的保証（.chat-bubble 不使用 + contentParts 非push）
- [ ] R10: テスト（reasoning_content/thinking_delta 拾い上げ・segments 保存・full_response 混入なし）
- [ ] R11: docs/llm_usage_guide.md に thinking_delta 追記
