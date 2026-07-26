# TODO — Phase 1: 検証・即時改善 (2026-07-26)

> SPEC: `.spec/SPEC.md` / PLAN: `.spec/PLAN.md` P1-1, P1-2
> 注意: フルテストスイートはメモリ不足のリスクあり。テストは対象ファイル指定で実行すること。

## P1-1: 記憶減衰・想起スコアの動作検証
- [ ] 1.1 DecayWorker デバッグログ追加（サイクル毎の処理/更新/スキップ件数）
- [ ] 1.2 オーファン memory_strength クリーンアップ migration 追加
- [ ] 1.3 strength_repo FK エラーログのサマリー集計化
- [ ] 1.4 減衰スコアが検索結果に反映されることの統合テスト追加

## P1-2: 応答検証の動作確認
- [ ] 2.1 全 PostProcessStep 検証パスの洗い出し・一覧化
- [ ] 2.2 キャラクター矛盾検出能力のテストケース作成
- [ ] 2.3 （検出不可の場合のみ）ルールベース後処理検証パス追加

## 検証
- [ ] V1: `pytest tests/unit/test_decay_worker.py tests/unit/test_memory_strength.py` + 新規
- [ ] V2: P1-2 新規テスト + test_chat_pipeline.py 関連部分
- [ ] V3: 変更モジュール依存テストの個別実行（フルスイート禁止）
- [ ] V4: `ruff check` PASS
- [ ] V5: 新規 migration の冪等性確認
