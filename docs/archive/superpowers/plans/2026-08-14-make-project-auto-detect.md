# make-project 自動検出拡張 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** make-project スキルに「プロジェクト判定」ステップを追加し、明らかにコーディングプロジェクトである場合のみ AGENTS.md 生成 + `project:<slug>` タグ付与を自動提案できるようにする。

**Architecture:** 変更は make-project スキルの指示書のみ。session-start ・ nous アプリ・プラグインは変更しない。検出は機械的条件式ではなく LLM 判断。生成は常にユーザー確認を挟む。

**Tech Stack:** なし（マークダウン指示書の編集）

## Global Constraints

- 変更ファイルは `data/skills/make-project/SKILL.md` と `~/.agents/skills/make-project/SKILL.md` の2箇所のみ（内容は同一に保つ）
- 判定は LLM がファイル一覧を見て判断。機械的条件式・ルールファイルを持たない
- 生成前に必ずユーザー確認（黙って生成しない）
- 既存 AGENTS.md がある場合は上書きしない
- session-start / nous アプリ / opencode プラグインは変更しない
- `.agent/` 等は一切生成しない（既存制約を維持）

---

### Task 1: SKILL.md に「プロジェクト判定」ステップを追加

**Files:**
- Modify: `data/skills/make-project/SKILL.md`（description 更新 + 手順冒頭に判定ステップ追加）
- Modify: `~/.agents/skills/make-project/SKILL.md`（同じ変更を反映）

**Interfaces:**
- Consumes: なし
- Produces: 手順 0「プロジェクト判定」節（判定表・確認フロー・AGENTS.md 保護ルール）。既存の手順 1〜5 は番号変更のみで内容不変

- [ ] **Step 1: description に自動検出を追記**

`data/skills/make-project/SKILL.md` の frontmatter description（L3）を更新し、自動検出の言及を追加する:

変更前:
```
description: "新規開発プロジェクトの初期構築スキル。プロジェクトの識別タグ決定・初期記憶の記録・生成ファイル一式（README / AGENTS.md / .spec/ / CLAUDE.md / GEMINI.md / .gitignore / git init）のテンプレート提示を行う。『プロジェクトを初期化して』『プロジェクトをセットアップして』『新規プロジェクトを始めたい』などのリクエストで必ず使用すること。"
```

変更後:
```
description: "新規開発プロジェクトの初期構築スキル。プロジェクトの識別タグ決定・初期記憶の記録・生成ファイル一式（README / AGENTS.md / .spec/ / CLAUDE.md / GEMINI.md / .gitignore / git init）のテンプレート提示を行う。コーディング開始・初期化リクエスト時にディレクトリ状態を検査し、明らかにコーディングプロジェクトと判断できる場合のみ AGENTS.md 生成とプロジェクトタグ付与を提案する（常にユーザー確認あり）。『プロジェクトを初期化して』『プロジェクトをセットアップして』『新規プロジェクトを始めたい』などのリクエストで必ず使用すること。"
```

- [ ] **Step 2: 手順冒頭に「プロジェクト判定」節を追加**

`## 手順`（L13）の直後に「### 0. プロジェクト判定」節を挿入する。既存の「### 1. 事前確認」以降は番号を変えずそのまま残す（番号は連番でなくてもよい。参照箇所は「手順 5」のような記載がないことを確認済み）。

挿入する内容:

```markdown
### 0. プロジェクト判定（自動検出）
コーディング開始・初期化リクエストを検知したら、まずカレントディレクトリを検査してプロジェクトか否かを判断する。判定は LLM（エージェント）がファイル一覧を見て行う。機械的な条件式は持たない。

| ディレクトリ状態 | 判定 | 動作 |
|---|---|---|
| 空 / 設定ファイルのみ（.vscode 等） | 通常会話 | スキップ（生成しない。通常の会話を継続） |
| コード・言語マニフェストあり（package.json / pyproject.toml / src/ / *.ts 等） | 明らかにコーディング | ユーザーに確認してから生成（下記フロー） |
| 状態が不明 | 不明 | ユーザーに質問して判断（質問1つのみで絞り込む） |

#### 確認フロー（常時）
1. 検出したら「AGENTS.md を生成して `project:<slug>` タグを付けますか？」と提案する
2. 承認 → 手順 1 に進む（slug・概要・技術構成はこのタイミングで確認）
3. 拒否 → 何も生成せず、通常の会話を継続する
4. 不明 → 質問してから判断する

#### 既存 AGENTS.md 保護
- 既に AGENTS.md が存在するディレクトリでは生成しない（上書き禁止）
- 既存 AGENTS.md がある場合は、そのまま既存運用を続ける
```

- [ ] **Step 3: 変更を `~/.agents/skills/make-project/SKILL.md` に反映**

同じ2箇所（description・手順0節）を `~/.agents/skills/make-project/SKILL.md` にも適用する（chezmoi externals 同期のクライアント実体）。

- [ ] **Step 4: 同一性・構文を検証**

```bash
diff data/skills/make-project/SKILL.md ~/.agents/skills/make-project/SKILL.md
# 期待: 出力なし（同一）
```

さらに frontmatter が閉じていること、追加節の見出しレベルが既存と揃っていること（`###`）を目視確認する。

- [ ] **Step 5: コミット**

```bash
cd /home/rausraus/code/Nous
git add data/skills/make-project/SKILL.md
git commit -m "feat(skill): make-project にプロジェクト判定（自動検出）ステップを追加
- ディレクトリ状態を検査し、明らかにコーディングプロジェクトのみ AGENTS.md 生成を提案
- 常にユーザー確認。既存 AGENTS.md は上書きしない
- 判定は LLM 判断（機械的条件式なし）。session-start / nous アプリは不変"
```

- [ ] **Step 6: 実地検証（3ケース）**

テストはスキル指示書のため自動テストなし。実セッションで以下を確認する:
1. 空ディレクトリ → スキップされる
2. コードあり → 検出 → 確認 → 承認で生成される
3. 不明 → 質問が発生する

※ ケース1〜3は今後の実セッションで逐次確認し、本コミットの検証としては diff 同一性 + 構文確認までとする。
