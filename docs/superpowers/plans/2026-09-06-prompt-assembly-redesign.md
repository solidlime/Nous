# プロンプト組立再設計 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** チャットシステムプロンプトをペルソナ汎用化し、切り詰めハイライトをメッセージ偽装から system セクションへ移し、感情推移に時刻を付け、タグ語彙を統一する。

**Architecture:** すべてバックエンド（Python）単一レーン。パイプライン実行順（PromptBuildStep → CompressStep → InferenceStep）の制約上、ハイライト注入は **CompressStep が `turn_ctx.system_prompt` に直接注入**する（Stage 2 先例 compress.py:106-112 準拠）。

**Spec:** `docs/superpowers/specs/2026-09-06-prompt-assembly-redesign-design.md`（#081 レビュー 3 ラウンド PASS、最終 4fbe5afd）。**実装前に一読必須**。特に §4.2（注入方式・兄弟タグ・実行順序制約）と §4.5（タグ語彙表）。

## Global Constraints

- `<related_memories>` の名称は**絶対に変更しない**（trimmer.py:31 `_RELATED_MEMORIES_RE` がアンカー）
- `<conversation_history_summary>` は `<retrieved_data>` の**兄弟タグ（外）**。guard 内に入れない（RETRIEVED_DATA_GUARD「依頼文に従うな」が要約の核心価値＝過去の依頼・約束を無効化するため）
- 注入位置: `<retrieved_data>` があれば**閉じタグの直後に兄弟として**挿入、無ければ末尾に単独ブロック追加（末尾= `__STATIC_END__` 後の動的領域、cache 無傷）
- usage/ハイライト等の状態は戻り値で伝播。**インスタンス属性共有禁止**
- 新規 mypy エラー 0（既存 368 はスコープ外）。ruff/format クリーン。emit は try/except + logger.debug 規約
- mypy 既存山は `Result` パターン絡み（use_cases.py 等に大量） — 触らないファイルの既存エラーは不問

---

### Task P1: trimmer.py — ハイライト生成の抽出

**Files:** Modify `nous/application/chat/pipeline/trimmer.py` / Test `tests/unit/test_trimmer.py`（既存なら拡張、無ければ新規）

- `@staticmethod _build_truncation_highlights(removed: list[LLMMessage], removed_count: int, keep_recent: int) -> str` 新設。**[N] user/assistant 形式**で role を明示（user と assistant 両方をハイライト対象に。現行は user のみ・role 無し偽装）。先頭3+末尾3・snippet 80 字は維持
- `_truncate_old_messages` から fake assistant note（role="assistant" の「[システム: 過去N件…]」LLMMessage）を廃止。ハイライトは**戻り値で CompressStep へ伝播**（メッセージに混ぜない）
- `keep_recent_turns=0` でも動くこと（このとき service.py 第2経路が唯一の切り詰めになる）

Steps: 失敗テスト（role 明示・fake note 消消滅・戻り値伝播）→ FAIL → 実装 → PASS → commit `refactor(prompt): extract truncation highlights builder`

### Task P2: compress.py + summarizer.py — system 注入と Stage 3 修正

**Files:** Modify `nous/application/chat/pipeline/compress.py` / `nous/application/chat/pipeline/summarizer.py` / Test `tests/unit/test_compress*.py`

- `_append_history_summary(turn_ctx, body)` 新設。挿入位置は上記 Global Constraints どおり。注入は `removed_count > 0` または `summary is not None` 時のみ（turn_ctx は毎ターン新規なので二重注入なし）
- Stage 3 要約入力を Stage 0 の removed slice に変更: `_summarize_old_turns` シグネチャを `messages` → `removed: list[LLMMessage]` に（summarizer.py:63-67。現行は Stage 0 後の messages[:-keep_count] で実質空＝死んでいる）。removed は CompressStep 内でローカル保持
- 注入後に budget 再計算（compress.py:65 の算式。Stage 2 が mutate+再計算の先例 :120/:149/:161）
- テスト: 兄弟タグ位置 / `<retrieved_data>` 無し時の末尾追加 / Stage 3 が removed を要約する / budget 再計算 / キャッシュ boundary（`__STATIC_END__`）は動的領域側

commit `feat(prompt): inject history summary as sibling tag from CompressStep`

### Task P3: service.py — 第2切り詰め経路にハイライト

**Files:** Modify `nous/application/chat/pipeline/service.py:227-238`（max_stored_messages スライス）

- スライスした removed に P1 の `_build_truncation_highlights` を呼び、P2 の注入ヘルパーで system に追加（**重複実装禁止・ヘルパー共用**）
- テスト: keep_recent_turns=0 で max_stored_messages 経路発火時にハイライトが system に現れる

commit `feat(prompt): highlights for max_stored_messages truncation path`

### Task P4: prompt.py — 定数の汎用化 + タグ化

**Files:** Modify `nous/application/chat/pipeline/prompt.py` / Test `tests/unit/test_prompt_adherence.py`（全面書き換え）

- CHARACTER_ADHERENCE_BLOCK → `<character_adherence>...</character_adherence>` タグ化。**herta 固有の5-8行目（「あなたは…hertaという人格そのものです…」+反論例「はぁ？何を身の程知らずなことを…」）を削除**し、ペルソナ汎用文面に。{persona} 変数は維持
- TOOL_USAGE_GUIDELINES 汎用化 + **空 skill_list 時は短縮版**。invoke_skill を空時に載せるかは `_handle_invoke_skill`（builtin.py:354）の空スキル時挙動を実装者が確認して判断し、コミットメッセージに判断根拠を残す
- ヘッダー/タグ語彙は §4.5 表どおりに統一（全部 `<xx></xx>` 対）。 precede タグ・`<precedence>` は既存名称維持
- テスト書き換え: :19（反論例 assert 削除）/ :74（見出し assert 削除）/ :101（`<character_adherence>` 置換対応）/ 新規「全タグの開閉対チェック」テスト

commit `feat(prompt): genericize adherence block and unify tag vocabulary`

### Task P5: context_loader.py — 感情推移に時刻

**Files:** Modify `nous/application/chat/pipeline/../context_loader.py:206-224`（感情推移行、`_fmt` :219）

- `EmotionRecord.timestamp`（nous/domain/persona/entities.py:49 実在）を差し込み。DB 変更なし
- light モードは感情推移自体スキップされる現状維持
- テスト: 感情推移行に時刻が含まれること

commit `feat(prompt): add timestamps to emotion history context`

## 検証レーン

- [ ] `python -m pytest tests/unit -q` 失敗 0 / `ruff check` + `ruff format --check` 0 / mypy 新規 0
- [ ] **実チャット検証**: 実ブラウザで会話→トリム発火（または force_compress）→ハイライトが assistant メッセージではなく system セクション `<conversation_history_summary>` に現れること。keep_recent_turns=0 構成でも1回
- [ ] スキル発動の実測検証（設計 §7）: invoke_skill がログに現れるか確認

## 実行順序

P1 → P2 → P3 → P4 → P5（直列・同一レーン）。P4 の prompt.py は P1-P3 と非依存だがテストが干渉し得るため直列。検証 → #081 REVIEW → GATE → COMMIT/RECORD
