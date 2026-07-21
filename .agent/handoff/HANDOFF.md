# HANDOFF — 2026-07-22 (セッション5: スキル自律動作テスト)

## セッション概要
5つの組み込みスキル（auto-memory, recall-weaver, mood-sync, goal-coach, image-gen）が LLM モデルによって自律的に呼び出されるかの検証。合計20コミット、3段階の作業。

## 完了コミット（全プッシュ済み main → origin/main）
```
# Phase 3: Spec + Final
765b0b2 feat: add skill_test.py for autonomous skill invocation verification
bc251f7 fix: harden prompt.py TOOL_USAGE_GUIDELINES for weaker model tool calling
cb42281 docs: update PLAN.md and SPEC.md for skill autonomous testing session

# Phase 2: Prompt/Tool Calling Fixes
4cc33a4 fix: add tool_choice=auto for OpenAI-compatible providers
4747749 fix: remove redundant identity statement from TOOL_USAGE_GUIDELINES
5111bb6 aa  (※typo commit, 後述)
d15a191 fix: skill invoke_skill が発動しない Lost in the Middle 問題を修正
94efc7b feat: add skill/tool invocation logging at 3 injection points

# Phase 1b: Skill Description Fixes
cce2a78 fix(image-gen): concrete trigger cues — replace vague 状況
72d85e6 fix(image-gen): add explicit image gen request trigger to description
13c24f0 fix(image-gen): rewrite description and body — persona-centric
876a207 fix(skills): repair descriptions — restore image-gen/general keywords

# Phase 1a: Transaction Fixes
844d800 fix: remove redundant commit() in session_store.py (autocommit mode)
2937070 fix: remove explicit commit from single-statement writes in entity_repo, session_event_repo
f8a0e2c fix: transaction fix for equipment_repo - Rule A/B applied
9b035a8 fix: add BEGIN IMMEDIATE to multi-statement writes, remove explicit commit/rollback
20c2ae4 fix: remove explicit commit/rollback from single-statement writes in strength_repo, block_repo
18c9f2b fix: add BEGIN IMMEDIATE to update_state, remove explicit commit from single-statement writes
ad58c93 fix: set isolation_level=None on sqlite3.connect for autocommit mode
95e8cfd fix: remove 5-turn frequency limit from image-gen, relax to per-turn
```

## 実装サマリ

### Phase 1a: トランザクション修正 (8 commits)
sqlite3 の autocommit モード（isolation_level=None）を導入し、単一文書き込みの explicit commit を除去。複数文書き込みには `BEGIN IMMEDIATE` を付与。
- **ルールA**: single-statement writes → commit/rollback不要（autocommit）
- **ルールB**: multi-statement writes → `BEGIN IMMEDIATE ... commit` 必須
- 影響範囲: session_store.py, entity_repo.py, session_event_repo.py, equipment_repo.py, strength_repo.py, block_repo.py

### Phase 1b: スキルDescription修正 (4 commits)
全5スキルの description/body を書き直し、発動トリガーを具体化。
- image-gen: 抽象的な「状況」→「表情・体勢・居場所」、prohibition削除
- mood-sync: context_note + relationship を追加
- goal-coach: 目標作成条件を明確化

### Phase 2: プロンプト最適化 (5 commits)
Lost in the Middle 問題の診断・修正。tool_choice=auto 追加。
- ログ注入点3箇所（pipeline入出力 + SSE）
- tool_usage ブロックの命令形強化
- 末尾リマインダーの3連命令形

### Phase 3: テスト + ドキュメント (3 commits)
最終テスト: Nemotron 3 Ultra で全5スキル 5/5 合格。
- skill_test.py: WebUI API経由のSSEストリーム検証スクリプト
- SPEC.md: 完全なテスト結果ドキュメント化

## 現在の状態
- バージョン: 3.5.0（変更なし）
- 作業ディレクトリ: clean (未追跡ファイルなし)
- テスト結果: 5/5 pass on `nvidia/nemotron-3-ultra-550b-a55b:free`

## 注意点
1. **commit 5111bb6 "aa"**: 誤コミット。内容はd15a191と同一で有害ではないが、rebaseかdrop推奨。
2. **OpenRouter無料モデルの寿命**: hy3:free, qwen3-coder:free は無料期間終了。Nemotronも予告なく終了しうる。
3. **tool_choice=auto**: OpenAI互換プロバイダでの弱いモデルのツール呼出に必須。Anthropicでは未検証。
4. **レート制限**: Nvidiaのfree tierは32並列制限あり。一括テストで429発生可能性。
5. **MEMORY.md**: 本セッションの重要教訓5件を記録済み。
