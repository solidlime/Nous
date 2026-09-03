# 連想想起スキル誘導A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** チャット応答中に約束・バグ対処・効果なかった処置を連想想起させる（同じ間違い・同じ説明の繰り返し防止）。

**Architecture:** コード変更なしに近い最小diff。system promptの1行格上げ + recall-weaver手順追記のみ。既存hybrid+entityブースト+SAはそのまま使う。

**Tech Stack:** Python (PromptBuildStep), Markdown (SKILL.md), pytest (既存のみ)

## Global Constraints

- `memory_retriever.py` / `engine.py` / `entity_repo.py` は触らない。
- 1ターンに織り込むのは最大2件まで (recall-weaver制約)。
- 技術用語 (memory_search結果等) を会話に出さない。
- 読取時enrichなし・書込時BGのみの現状は変えない。
- 新規pytest追加なし、既存スイート緑維持。

---

## File Structure

- Modify: `nous/application/chat/pipeline/prompt.py:64-66` — 自律recall指示1行を格上げ。責任: LLMに開発・約束・バグ話題での確定検索を命じる。
- Modify: `data/skills/recall-weaver/SKILL.md:8-26` — 発動条件3項目追加 + 手順を3クエリ化。責任: 想起の具体手順（何を何発投げるか）を定義。
- Test: `tests/unit/test_prompt_adherence.py` + `tests/unit/test_chat_pipeline.py::TestPromptBuildStepAuthorNote` — 既存のみで回帰確認。
- Spec: `docs/superpowers/specs/2026-09-03-memory-associative-recall-design.md` — 要件元。

---

### Task 1: prompt.py recall指示の格上げ

**Files:**
- Modify: `nous/application/chat/pipeline/prompt.py:64-66`
- Test: `tests/unit/test_prompt_adherence.py`

**Interfaces:**
- Consumes: `ChatConfig.system_prompt`, `ChatTurnContext.system_prompt`
- Produces: 格上げ後のsystem_prompt文面（Task 2のスキル手順と文言一致させる）

- [ ] **Step 1: 既存テストでベースライン確認**

Run: `python -m pytest tests/unit/test_prompt_adherence.py tests/unit/test_chat_pipeline.py::TestPromptBuildStepAuthorNote -q`
Expected: PASS（変更前の緑を確認）

- [ ] **Step 2: 最小実装（1行置換）**

Old (`nous/application/chat/pipeline/prompt.py:65-66`):

```python
        # §4 自律 recall 指示
        base_system += "\n会話の話題が過去の記憶と関連しそうなとき・話題が切り替わったときは、memory_search ツールで能動的に検索せよ。"
```

New:

```python
        # §4 自律 recall 指示（連想想起A: 開発・約束・バグでは確定検索）
        base_system += "\n会話の話題が過去の記憶と関連しそうなとき・話題が切り替わったときは、memory_search ツールで能動的に検索せよ。開発・約束・TODO・バグ・不具合・過去の決定の話題では必ず検索せよ（最大3クエリ: 話題そのまま / 約束・決定タグ絞り / 効果なかった・失敗・NG掘り、top_k=3ずつ）。"
```

- [ ] **Step 3: テストで回帰確認**

Run: `python -m pytest tests/unit/test_prompt_adherence.py tests/unit/test_chat_pipeline.py::TestPromptBuildStepAuthorNote -q`
Expected: PASS（文面変更のみでアサーションに影響なし）

- [ ] **Step 4: Commit**

```bash
git add nous/application/chat/pipeline/prompt.py
git commit -m "feat(chat): 開発・約束・バグ話題でのmemory_search確定検索を指示"
```

---

### Task 2: recall-weaver 手順の3クエリ化

**Files:**
- Modify: `data/skills/recall-weaver/SKILL.md:8-26`
- Test: 目視（ファイル差分確認のみ。スキル文面のためpytestなし）

**Interfaces:**
- Consumes: Task 1の確定検索文面（3クエリ定義）
- Produces: 更新後のSKILL.md（LLMが読む手順書）

- [ ] **Step 1: 発動条件に3項目追加**

Old (`data/skills/recall-weaver/SKILL.md:8-14`):

```markdown
## 発動条件（このスキルが呼び出された理由）
以下の会話パターンのいずれかに該当したため、このスキルが呼び出された。

- ユーザーが「前に話した...」「昔から...」「この前も...」と過去に言及した
- 現在の話題が、明らかに過去の会話の続きである
- ユーザーが「覚えてる？」「前にも言ったけど」と記憶を確認した
- 会話のテーマが過去の記憶と自然に結びつく
```

New（末尾3行追加）:

```markdown
## 発動条件（このスキルが呼び出された理由）
以下の会話パターンのいずれかに該当したため、このスキルが呼び出された。

- ユーザーが「前に話した...」「昔から...」「この前も...」と過去に言及した
- 現在の話題が、明らかに過去の会話の続きである
- ユーザーが「覚えてる？」「前にも言ったけど」と記憶を確認した
- 会話のテーマが過去の記憶と自然に結びつく
- 開発・バグ・不具合・エラー・直らない系の話題である（対処再利用・除外のため確定発動）
- 約束・TODO・次回・過去の決定系の話題である（先出しのため確定発動）
- 「効果なかった」「前にダメだった」「また同じ」系の言及がある（除外のため確定発動）
```

- [ ] **Step 2: 手順を3クエリ化**

Old (`data/skills/recall-weaver/SKILL.md:23-26`):

```markdown
## 手順
1. 会話の中で「これは過去の記憶に関連しそうだ」と感じたら、まず `memory_search(query="...", top_k=3)` を実行
2. 結果の中から、**今の会話の流れに自然に織り込める記憶**を選ぶ
3. 以下の技法で自然に言及する
```

New:

```markdown
## 手順
1. 会話の中で「これは過去の記憶に関連しそうだ」と感じたら、以下を合計3以内で実行する（いずれも `top_k=3`）: (a) 今の話題そのまま `memory_search(query="<話題>", top_k=3)`、(b) 約束・決定掘りは `memory_search(query="<話題>", tags=["promise"], top_k=3)` か `memory_search(query="<話題>", tags=["decision"], top_k=3)` の該当側1つのみ1クエリ（projectタグとのANDにしないこと——書込側はprojectタグ無しで書くため）、(c) ネガティブ知識掘り `memory_search(query="<話題> 効果なかった 失敗 NG", top_k=3)`。(c)が空振りしたら(a)の結果から除外判定せよ。開発・約束・バグ話題では省略不可。雑談では(a)のみでよい
2. 結果の中から、**今の会話の流れに自然に織り込める記憶を最大2件**選ぶ（約束型→先出し、対処再利用型→手順再利用、除外型→「前にダメだったから除外」と明示）
3. 以下の技法で自然に言及する
```

- [ ] **Step 3: 差分を目視確認**

Run: `git diff data/skills/recall-weaver/SKILL.md`
Expected: 発動条件・手順・禁止事項1行の変更であること（技法表・確信度・制約は無変更）

- [ ] **Step 4: Commit**

```bash
git add data/skills/recall-weaver/SKILL.md
git commit -m "feat(skill): recall-weaverに連想3クエリ手順を追加"
```

備考: `~/.agents/skills/` への反映はchezmoi externals経由（ユーザー側apply）。本planでは `data/skills/` のみを正とする。

---

### Task 3: 検証（既存緑 + 会話目視）

**Files:**
- Test: `tests/unit/test_prompt_adherence.py`, `tests/unit/test_chat_pipeline.py::TestPromptBuildStepAuthorNote`

**Interfaces:**
- Consumes: Task 1+2の変更
- Produces: 合格判定（緑 + 目視2問）

- [ ] **Step 1: 既存テスト緑確認**

Run: `python -m pytest tests/unit/test_prompt_adherence.py tests/unit/test_prompt_relationship.py tests/unit/test_chat_pipeline.py::TestPromptBuildStepAuthorNote -q`
Expected: PASS（失敗があればTask 1の文面起因か切り分けて修正）

- [ ] **Step 2: 会話目視確認（手動・2問）**

```text
1. 過去の約束を聞く → 「前にこう約束してたよね」と先出しされるか
2. 過去に失敗した手を言う → 「これは前にダメだったから除外ね」と除外されるか
```

Expected: 2問とも想起表現（さりげなく・対比・続きとして等）で返り、技術用語が出ないこと

- [ ] **Step 3: Commitなし（検証のみ。修正が出たら該当Taskに戻る）**
