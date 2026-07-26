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
