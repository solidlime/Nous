# [DEPRECATED] CI Failure Auto-Triage Loop 実装計画（改訂版）

> **⚠️ この計画は破棄されました（2026-07-20）。**
> CI自動トリアージは廃止。品質ゲートは `make_project_skill` に統合。
> 参照: `.agents/AGENTS.md` → `make_project_skill/SKILL.md`

> **For agentic workers:** ~~本計画はグローバルスキル `.agents/skills/ci-triage/SKILL.md` に基づき、
> 品質ゲート `EXPLORE → PLAN → IMPLEMENT → TEST → REVIEW → GATE → COMMIT → PUSH` に従う。~~
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CI失敗を自動検出し、構造化診断レポートを生成。OpenCode orchestrator が Maker-Checker 品質ゲートパイプラインで修正ループを回すグローバルスキルを構築する。

**Architecture:**
```
GitHub Actions (workflow_run) → ci-triage.yml → Issue (label: ci-triage)
    │
    ▼
Orchestrator (ci-triage スキルロード)
    │
    ├─ Phase 1: EXPLORE  → orchestrator + @explorer
    ├─ Phase 2: PLAN     → orchestrator
    ├─ Phase 3: IMPLEMENT → @fixer (#011)
    ├─ Phase 4: TEST     → @fixer → orchestrator確認
    ├─ Phase 5: REVIEW   → @oracle (#081)  PASS or BLOCK
    ├─ Phase 6: GATE     → orchestrator 全チェック通過確認
    ├─ Phase 7: COMMIT+PUSH → orchestrator
    └─ Phase 8: 後処理    → loop-ledger.json / Issue / MEMORY.md 更新
```

**Tech Stack:** GitHub Actions (`workflow_run`), `gh` CLI, OpenCode sub-agents (@fixer + @oracle + @explorer), loop-ledger.json

**成果物:**
- グローバルスキル: `.agents/skills/ci-triage/SKILL.md`
- テンプレート: `.agents/skills/ci-triage/templates/ci-triage.yml` + `loop-ledger.json`
- make_project_skill 統合: `make_project_skill/SKILL.md` §6 にCIトリアージ設定を追加

---

## Task 0: グローバルスキル作成（完了）

**Files:**
- Create: `.agents/skills/ci-triage/SKILL.md` ✅
- Create: `.agents/skills/ci-triage/templates/ci-triage.yml` ✅
- Create: `.agents/skills/ci-triage/templates/loop-ledger.json` ✅

---

## Task 1: make_project_skill 統合（完了）

**Files:**
- Modify: `.agents/skills/make_project_skill/SKILL.md` §6 追加 ✅

新規プロジェクト作成時に「CI自動トリアージを設定しますか？」を確認し、Yes なら Part A のセットアップを実行する。

---

## Task 2: Nous プロジェクトにCIトリアージを導入

**Files:**
- Create: `code/Nous/.github/workflows/ci-triage.yml` ← テンプレートからコピー
- Create: `code/Nous/.agent/loop-ledger.json` ← テンプレートからコピー
- Modify: `code/Nous/.agent/memory/MEMORY.md` ← CIトリアージ設定を記録

### 手順

- [ ] **Step 1: テンプレートをコピー**

```bash
cp .agents/skills/ci-triage/templates/ci-triage.yml code/Nous/.github/workflows/ci-triage.yml
cp .agents/skills/ci-triage/templates/loop-ledger.json code/Nous/.agent/loop-ledger.json
```

- [ ] **Step 2: CIワークフロー名を確認**

Nous のCIワークフロー名は `CI`（`code/Nous/.github/workflows/ci.yml` の `name: CI` より）。
テンプレートのデフォルト値 `workflows: ["CI"]` で合致しているため修正不要。

- [ ] **Step 3: MEMORY.md にCIトリアージ設定を追記**

`code/Nous/.agent/memory/MEMORY.md` に以下を追記:
```markdown
## CI Auto-Triage
- セットアップ日: 2026-07-20
- CIワークフロー名: CI
- 監視対象: push to main, PR open/sync/reopen, merge_group
- 状態: active
```

- [ ] **Step 4: commit & push**

```bash
cd code/Nous
git add .github/workflows/ci-triage.yml .agent/loop-ledger.json .agent/memory/MEMORY.md
git commit -m "feat: add CI auto-triage loop"
git push
```

---

## Task 3: MCP-Hub プロジェクトにCIトリアージを導入

**Files:**
- Create: `code/MCP-Hub/.github/workflows/ci-triage.yml` ← テンプレートからコピー
- Create: `code/MCP-Hub/.agent/loop-ledger.json` ← テンプレートからコピー
- Modify: `code/MCP-Hub/.agent/memory/MEMORY.md` ← CIトリアージ設定を記録（なければ新規作成）

### 手順

- [ ] **Step 1: テンプレートをコピー**

```bash
cp .agents/skills/ci-triage/templates/ci-triage.yml code/MCP-Hub/.github/workflows/ci-triage.yml
cp .agents/skills/ci-triage/templates/loop-ledger.json code/MCP-Hub/.agent/loop-ledger.json
```

- [ ] **Step 2: CIワークフロー名を確認**

MCP-Hub のCIワークフロー名は `CI`（`code/MCP-Hub/.github/workflows/ci.yml` の `name: CI` より）。
テンプレートのデフォルト値 `workflows: ["CI"]` で合致しているため修正不要。

- [ ] **Step 3: .agent ディレクトリを作成し MEMORY.md を作成**

```bash
mkdir -p code/MCP-Hub/.agent/memory
```

```markdown
# MEMORY

## プロジェクト概要
MCP-Hub: MCPサーバー管理CLIツール

## CI Auto-Triage
- セットアップ日: 2026-07-20
- CIワークフロー名: CI
- 監視対象: push to main, PR open/sync/reopen
- 状態: active
```

- [ ] **Step 4: commit & push**

```bash
cd code/MCP-Hub
git add .github/workflows/ci-triage.yml .agent/
git commit -m "feat: add CI auto-triage loop"
git push
```

---

## Task 4: 検証

- [ ] **Step 1: スキルファイルの構造確認**

```bash
echo "=== Global skill structure ==="
ls -la .agents/skills/ci-triage/
ls -la .agents/skills/ci-triage/templates/

echo "=== SKILL.md sections ==="
grep -c "Phase [0-9]" .agents/skills/ci-triage/SKILL.md
grep -c "Part [A-E]" .agents/skills/ci-triage/SKILL.md
grep "通過条件" .agents/skills/ci-triage/SKILL.md | wc -l
```

期待値: 8つのPhase、5つのPart、8つの通過条件ブロック

- [ ] **Step 2: テンプレートYAML構文確認**

```bash
python3 -c "import yaml; yaml.safe_load(open('.agents/skills/ci-triage/templates/ci-triage.yml'))" && echo "YAML syntax OK"
```

- [ ] **Step 3: make_project_skill にCIトリアージセクションが存在するか確認**

```bash
grep -A2 "CI自動トリアージ" .agents/skills/make_project_skill/SKILL.md | head -5
```

- [ ] **Step 4: loop-ledger.json が有効なJSONか確認**

```bash
python3 -c "import json; json.load(open('.agents/skills/ci-triage/templates/loop-ledger.json'))" && echo "JSON syntax OK"
```

- [ ] **Step 5: プロジェクト側CIファイルの確認**

```bash
echo "=== Nous ==="
ls -l code/Nous/.github/workflows/ci-triage.yml && echo "ci-triage.yml: OK" || echo "MISSING"
ls -l code/Nous/.agent/loop-ledger.json && echo "loop-ledger.json: OK" || echo "MISSING"

echo "=== MCP-Hub ==="
ls -l code/MCP-Hub/.github/workflows/ci-triage.yml && echo "ci-triage.yml: OK" || echo "MISSING"
ls -l code/MCP-Hub/.agent/loop-ledger.json && echo "loop-ledger.json: OK" || echo "MISSING"
```

---

## 品質ゲート一覧（本ループ内）

| フェーズ | 担当 | 通過条件 | 失敗時 |
|---------|------|---------|--------|
| **EXPLORE** | orch + @explorer | 失敗種別特定 + 関連ファイル1件以上 + 早期リジェクト非該当 | 手動調査エスカレーション |
| **PLAN** | orchestrator | 修正計画 ≤3ファイル, <100行, root causeベース | エスカレーション |
| **IMPLEMENT** | @fixer (#011) | 修正完了, ≤3ファイル, <100行, Drive-by対処済 | 再試行（max 3） |
| **TEST** | @fixer → orch | Lint/Formatter/型/Tests 全PASS, 既存壊しなし | #011差し戻し or #081判断 |
| **REVIEW** | @oracle (#081) | PASS = 完全。BLOCK = 上書き禁止 | 回路ブレーカー発動 |
| **GATE** | orchestrator | TEST + REVIEW 両方PASS, 全Drive-by対処済 | エスカレーション |
| **COMMIT+PUSH** | orchestrator | コミット成功 + プッシュ成功 + PR作成 | 手動介入 |
