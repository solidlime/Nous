# TODO — Nousツール レビュー対策 v2 (oracle review反映)

## Phase 0: クリティカルフィックス (P0) — 並列実行可

### T01: リランカー統合 🔴 ⚠️ 最高リスク ✅ DONE
- [x] **T01a**: `AppContext.__init__()` で `RerankerModel` をインスタンス化（`nous/application/use_cases.py`）
- [x] **T01b**: SearchEngine が `_reranker` 参照を持つよう修正（`__init__`パラメータ＋`_hybrid_search`での利用）
- [x] **T01c**: `SearchEngine._hybrid_search()` のRRF+dedup後に `self._reranker.rerank()` 呼出追加（`nous/domain/search/engine.py`）
- [ ] ~~**T01d**: `contents` dictをバッチ取得する `memory_repo.get_by_keys()` 呼出追加~~ — 不要: 結果はSearchResultとして既にメモリ上にある
- [x] **T01e**: モデルプリロード機構（daemon thread + try/except、同期ブロッキング回避）
- [x] **T01f**: ホットリロードコールバック修正（SearchEngineリセット追加、`_reranker`ガードは動作する）
- [x] **T01g**: 統合テスト追加（`tests/unit/test_reranker_integration.py` — 12 tests）
- **依存**: なし
- **担当**: @fixer（設計相談は@oracle）

### T02: エラーメッセージ英語統一 🔴
- [ ] **T02a**: 全 `nous_` ツールのエラーメッセージgrep→日本語→英語に置換
- [ ] **T02b**: テストのエラーメッセージ期待値も更新
- **依存**: なし
- **担当**: @fixer

### T03: read_pdf パス解決バグ修正 ✅
- [x] **T03a**: `nous_read_pdf` のパス解決ロジック調査 — sandbox環境とnousコンテナの分離が原因
- [x] **T03b**: 修正実装 — `/home/sbox_*` / `/sandbox` パスをsandbox session経由で読み取り
- [x] **T03c**: テストPDF動作確認 — 実ファイル＋モックテスト15件pass
- **担当**: @fixer

## Phase 0.5: 感情コンテキスト即時対応 (P0.5) ← 新設

### T04: emotion trigger_key 即時活用 🔴 ✅ DONE
- [x] **T04a**: `update_emotion()` の全呼出箇所（`memory_llm.py:377`, `builtin.py:74`, `_tools_persona.py:145`, `emotion_decay.py:59`）に `trigger_memory_key` と `context` を渡す
- [x] **T04b**: 感情トレンド表示に因果関係を追加（`_tools_helpers.py`, `prepare.py`）
- [x] **T04c**: テスト更新
- **依存**: なし（最小限の変更、数行）
- **担当**: @fixer

## Phase 1: 最重要 — 時間経過認識・感情強化 (P1)

### T05: 感情減衰の通知強化 🟡 ✅
- [x] **T05a**: `get_context()` 時に減衰前感情→減衰後感情を明示表示（`_tools_persona.py`, `_tools_helpers.py`）
- [x] **T05b**: 例: `anger(0.72)→neutral — faded over 48h`
- [x] **T05c**: テスト更新（6 tests追加）
- **依存**: T04（trigger_keyが使える前提）
- **担当**: @fixer

### T06: 感情持続性の概念（半減期×強度）🟡 ✅ DONE
- [x] **T06a**: `emotion_decay.py` の減衰計算を `effective_half_life = base_half_life * intensity` に変更
- [x] **T06b**: テスト更新
- **依存**: なし
- **担当**: @fixer

### T07: 感情半減期の設定化 🟡 ✅
- [x] **T07a**: `ForgettingConfig` に `emotion_half_life_hours: float = 24.0` 追加（`nous/config/settings.py`）
- [x] **T07b**: `emotion_decay.py` の `_EMOTION_HALF_LIFE` ハードコードを設定値参照に変更（`half_life_hours` パラメータとして注入）
- [x] **T07c**: runtime_config SETTINGS_META に `emotion_half_life_hours` 追加（hot_reload=True）
- [x] **T07d**: WebUI settings.js の BUILTIN_PROFILES forgetting セクションに追加
- [x] **T07e**: テスト追加（custom half-life affects decay rate, apply_if_needed passes through, settings default）
- **依存**: T06（持続性の概念が先）
- **担当**: @fixer

### T08: TIME GAP コメントの体験層化 🟡 ✅
- [x] **T08a**: `_tools_helpers.py` に `_generate_time_passage_narrative()` 追加 — テンプレートベース自然言語生成
- [x] **T08b**: 経過時間 + 身体状態変化 + 直近会話トピック（`recent[0].content`） + 感情減衰を自然に記述
- [x] **T08c**: <1h: "holds steady", 1-24h: body+emotion, >24h: body+topic+emotion の3段階
- [x] **T08d**: `_format_lightweight_response` に `elapsed_hours` / `emotion_decay_result` パラメータ追加
- [x] **T08e**: `_tools_persona.py` で elapsed_hours 計算 + emotion_decay_result を渡す
- [x] **T08f**: `prepare.py` の時間経過メッセージを日本語→英語に変更
- [x] **T08g**: テスト追加（6 tests: short/medium/long/zero/no-emotion/no-body）
- **依存**: T04, T05（trigger_key, 減衰通知）
- **担当**: @fixer

## Phase 2: 機能追加 (P1-P2)

### T09: スキルプリインストール 🟡 ✅
- [x] **T09a**: `verification-before-completion`, `systematic-debugging`, `test-driven-development` スキル登録
- [x] **T09b**: `nous_list_skills` が空でない確認テスト
- **依存**: なし
- **担当**: @fixer（調査は@explorer）

### T10: セッション自動記憶抽出（autoCapture）🟡 ✅ DONE
- [x] **T10a**: `PostProcessStep` にセッション内容からの重要情報抽出ロジック追加
- [x] **T10b**: 抽出情報の `memory_create` 自動保存
- [x] **T10c**: 設定でON/OFF切替可能に
- [x] **T10d**: テスト追加
- **依存**: なし
- **担当**: @fixer

## Phase 3: 基盤・ドキュメント (P2-P3)

### T11: body_state_history テーブル新設 🟢（P2に降格）✅
- [x] **T11a**: `body_state_history` テーブル作成（migration + `connection.py`）
- [x] **T11b**: `add_body_state_record()`, `get_body_state_history()` 追加（`persona_repo.py`）
- [x] **T11c**: `apply_body_decay_if_needed` で履歴記録（`body_decay.py`）
- [x] **T11d**: テスト追加
- **依存**: なし
- **担当**: @fixer

### T12: ドキュメント拡充 🟢
- [ ] **T12a**: README.md: 全ツール使用例追加
- [ ] **T12b**: README.md: セットアップ手順明確化
- [ ] **T12c**: README.md: トラブルシューティングセクション
- [ ] **T12d**: `docs/llm_usage_guide.md` 更新（エラーメッセージ変更反映）
- **依存**: Phase 0-2 完了後
- **担当**: @fixer

### T13: 外部ストレージ基盤 🟢（P3に降格）
- [x] **T13a**: `PersonaRepository` 抽象インターフェース定義（ABC）
- [x] **T13b**: 既存 `SQLitePersonaRepository` をインターフェース準拠にリファクタ（継承）
- [x] **T13c**: テスト更新（isinstance/abstract instantiation）
- **依存**: なし
- **担当**: @fixer（設計レビュー:@oracle）

### T14: goal_manage 重要度ラベル表示 🟢（P3、スコープ縮小）
- [ ] **T14a**: `importance → ラベル` コンバータ実装（≥0.9=critical, ≥0.7=high, ≥0.4=normal, <0.4=low）
- [ ] **T14b**: `goal_manage(list)` にラベル付与
- [ ] **T14c**: テスト追加
- **依存**: なし
- **担当**: @fixer

## Phase B: ペルソナ動的画像生成 (B0-B2)

### TB05: ComfyUI ImageGenProvider 🟢 ✅
- [x] **TB05a**: `ComfyUIProvider` 実装（`nous/infrastructure/image_gen/comfyui.py`）
- [x] **TB05b**: `ImageGenConfig` に `comfyui_url` 追加（`base.py`）
- [x] **TB05c**: factory に `"comfyui"` ケース追加（`factory.py`）
- [x] **TB05d**: テスト12件追加（healthcheck/generate/workflow/timeout/retry）
- **依存**: なし
- **担当**: @fixer

### TB06: ComfyUI ヘルスチェック 🟢 ✅
- [x] **TB06a**: `health_check()` メソッド実装（GET /system_stats）
- [x] **TB06b**: 接続エラー・非200時のフォールバック
- [x] **TB06c**: テスト3件（正常系/接続エラー/非200）
- **依存**: TB05
- **担当**: @fixer

---

## 実行順序（修正後）

```
Phase 0:    [T01, T02, T03] → 3並列
Phase 0.5:  [T04] → T01-T03完了後（独立だが、T01完了でAppContextが安定）
Phase 1:    [T06] → [T05, T07] → [T08]
Phase 2:    [T09, T10] → 2並列
Phase 3:    [T11, T13, T14] → 3並列 → [T12]
```

## 検証ゲート
各Phase完了後:
1. `python -m pytest tests/ -x --tb=short` → 全テスト通過
2. `ruff check .` → 0 errors
3. `git commit && git push` → GitHub Actionsパス
