---
name: make-project
description: "新規開発プロジェクトの初期構築スキル。プロジェクトの識別タグ決定・初期記憶の記録・生成ファイル一式（README / AGENTS.md / .spec/ / CLAUDE.md / GEMINI.md / .gitignore / git init）のテンプレート提示を行う。『プロジェクトを初期化して』『プロジェクトをセットアップして』『新規プロジェクトを始めたい』などのリクエストで必ず使用すること。"
---

# make-project — プロジェクト初期構築

## 設計思想
- プロジェクトの記憶・引継は全て nous 記憶システムに記録する（`.agent/` 等のファイル運用はしない）
- プロジェクトは **`project:<slug>` タグ**で識別する。このタグが全記憶の共通キーになる
- ファイル生成はユーザー側のエージェントが行う。このスキルは「記憶の初期化」と「生成すべきファイルの指示（テンプレート）」を担う

## 手順

### 1. 事前確認
以下の情報をユーザーに確認する（曖昧なら推測して確認を取る）:
- **slug**: プロジェクト識別子（英数字・ハイフンのみ。例: `nous-unification`）
- プロジェクトの目的・概要
- 技術構成・言語
- GitHub リポジトリ URL（あれば。事前に空リポジトリを作成しておくこと）

### 2. 重複確認
`memory_search(query="<slug>", tags=["project:<slug>"])` を実行し、既に同名プロジェクトが存在しないか確認する。
存在する場合はユーザーに報告し、新しい slug を提案する。

### 3. 初期記憶の記録
以下を `memory_create` で記録する:

```
memory_create(
    content="プロジェクト「<名前>」を開始。目的: <概要>。技術構成: <技術>。プロジェクト識別タグ: project:<slug>",
    importance=0.8,
    tags=["project:<slug>", "project_overview"],
    kind="semantic"
)
```

必要なら追加で:
- 初期の目標（あれば）: `tags=["project:<slug>", "goal"]`, `kind="prospective"`

### 4. ファイル生成（ユーザー側エージェントが実行）
以下をプロジェクトルートに生成する。テンプレートはそのまま使える形で記載している。

#### 4.1 README.md

```markdown
# <プロジェクト名>

<プロジェクト概要（1-2文）>

## 技術構成
- <言語・フレームワーク>
```

#### 4.2 AGENTS.md

以下の節で構成する。**`## プロジェクト識別` 節は必ず含める**こと（session-start スキルがこの節からタグを読み取る）。

```markdown
# Project guide line

## 1. プロジェクト概要
- 本プロジェクトのプラン作成、および回答は全て日本語で行います。
- <プロジェクト概要>

## 2. プロジェクト識別
- project: <slug>

# Nous 記憶運用（.agent/ は使わない）

## セッション開始時（必須）
セッション開始時、ユーザーへの最初の応答の前に session-start スキルを実行し、nous 記憶から状態を復元する:
- `get_context` でペルソナ状態・直近サマリを取得
- `## プロジェクト識別` 節から `project: <slug>` タグを取得
- `memory_search(tags=["project:<slug>", "task_state"], top_k=3)` 等で作業状態を復元
- `memory_search(tags=["session_summary"], top_k=1, sort="updated_at")` で前回の内容を把握

## メモリ管理
- 重要情報・決定・作業完了は nous に記録。`project:<slug>` タグ必須
- 状態変化時は `update_context` → `memory_create` の順で永続化
- `.agent/memory/MEMORY.md` / `.agent/handoff/HANDOFF.md` は使用しない（nous 記憶が代替）
- ローカルの自動メモリ機能（~/.claude/ 配下）は使用しない

## ハンドオフ管理
- セッション終了時の session_summary 生成（終了フック）が引継を代替する
- 手動引継が必要な場合は `memory_create(tags=["project:<slug>", "task_state"])` で記録

## 仕様駆動開発（SDD）ルール
- コーディングや業務作業を開始する前に、必ず `.spec/` 配下の4ファイルを確認・更新すること
- 作業の順序：PLAN（目的確認）→ SPEC（要件確認）→ TODO（タスク確認）→ 実作業
- **PLAN.mdは人間の口頭メモ・自由記述**であり、箇条書き・口語・断片的な内容で構わない
- PLAN.mdを読んだら、そのまま実装に入らず、不明点をヒアリングしながらSPEC.mdを作成・確定させること
- SPEC.mdが確定してからTODO.mdのタスク分解を行い、ユーザーの承認を得てから実作業を開始する
- 作業完了後は TODO.md の該当タスクにチェックを入れ、KNOWLEDGE.md に学びを記録する
- 仕様が不明確な場合は作業を開始せず、ユーザーに確認してから SPEC.md を更新する
```

#### 4.3 品質ゲート節（AGENTS.md の末尾に追記）

```markdown
## 品質ゲート

### トリアージ（3段階）
作業開始前にレベルを判定し、ゲートの重みを変える。

| レベル | 対象 | ゲート |
|--------|------|--------|
| 軽量 | 単一ファイル20行未満・機械的・1文で説明できるdiff | lint + 型チェック + 影響範囲テストのみ。REVIEW 省略可 |
| 標準 | 単一機能（数百行以内・ファイル分散 ≤5） | フルパイプライン（下記） |
| 本格 | 複数ファイル・アーキテクチャ/API/UI変更 | フル + 事前アーキテクチャ判断（#081）+ 実ブラウザ確認 + 契約テスト |

### パイプライン（検証ループ方式）
**EXPLORE** → **PLAN** → **IMPLEMENT** → **TEST**（検証ループ） → **REVIEW** → **GATE**（機械的条件式） → **COMMIT** → **PUSH**

各フェーズは Grill 方式で開始する: Goal（何を達成するか）→ Success criteria（どうなれば成功か）→ Success type（test / build / lint / command / fileExists）→ Execute agent / Verify agent を分離 → Max attempts（デフォルト3）→ 必要なら Context files。

| フェーズ | 担当 | やること | 通過条件 | 失敗時 |
|---------|------|---------|---------|--------|
| **EXPLORE** | #009 or orchestrator | コードベース探索、関連ファイル特定、依存関係把握 | 変更範囲が明確になっている | PLAN に進めない（再探索） |
| **PLAN** | orchestrator（委譲禁止） | 実装計画書の作成。影響範囲・ファイル一覧・テスト方針を明記 | 計画に具体性がある（ファイルパス・変更内容） | IMPLEMENT に進めない（計画の練り直し） |
| **IMPLEMENT** | #011（複数ファイルは並列）or 直接 | 計画に従い実装。単一ファイル20行未満は直接、それ以外は #011 | コードが計画通りに書かれている | TEST に進めない（#011 に差し戻し） |
| **TEST** | #011（Execute）+ 検証エージェント（Verify） | 検証ループ（下記「TEST = 検証ループ」参照） | 全チェック通過 | max3 再試行 → 人間エスカレーション |
| **REVIEW** | #081（oracle・独立コンテキスト） | diff + 基準のみを見て correctness のギャップを反駁。スタイル好みは指摘しない。編集権限なし | **PASS（完全）**。それ以外は BLOCK | BLOCK → IMPLEMENT に戻る。BLOCK を上書き禁止 |
| **GATE** | orchestrator | 機械的条件式（下記）で全項目を判定 | 条件式が成立 | COMMIT 禁止。未解決項目を修正 |
| **COMMIT** | orchestrator | `git add` + `git commit`。バグ修正は重大度に応じたプレフィックス | コミット成功 | — |
| **PUSH** | orchestrator | `git push` | プッシュ成功 | コンフリクト時は解決して再コミット |

### TEST = 検証ループ
1. **Execute**: 実装エージェント（#011）が変更を適用。
2. **Verify**: 検証エージェントが successCommand を実行して成功を機械判定する:
   - テスト: 全テスト失敗 0
   - 型チェック: exit 0（lint 通過 ≠ コンパイル通過）
   - lint/format: エラー 0
   - カバレッジ: ≥60%（プロジェクト規模で調整）
3. **失敗時**: エラー出力を Execute に返して再試行。max attempts = 3。
4. **3回失敗** → onEscalated: 人間へ理由付きでエスカレーション。自動解決禁止。
5. **手動レビューが必要な変更** → onManualReview: 人間が approve/fail を判定し、resolveManualReview まで COMMIT 禁止。
6. **onLoopComplete**: 結果と試行回数を記録して GATE へ。

### GATE = 機械的条件式
```
TYPECHECK=pass AND TESTS=0-fail AND COVERAGE≥60% AND LINT=0 AND FORMAT=ok
AND CONTRACT=pass AND SECRETS=0 AND AUDIT≤moderate AND DOCS=synced
AND DIFF=単一目的（300-500行以内、1000行超は分割、50ファイル分散は過大）
AND 禁止操作なし
```
- CONTRACT: 契約テスト（マイクロサービス構成なら Pact 等）が pass。
- SECRETS: シークレット検出（gitleaks）0件。
- AUDIT: 依存監査（`npm audit --audit-level=moderate`）が moderate 以下。
- DOCS: 公開API・CLIフラグ・env var 変更時は README / .env.example / APIドキュメントを同期更新（`documentation-sync` を参照）。
- 禁止操作: `git push --force` / `git commit --no-verify` / `DROP TABLE` / `DELETE FROM` なし。

### CI 二重ゲート
- **第1ゲート（ローカル）**: pre-commit で lint/format を変更分のみ高速実行（速度優先）。
- **第2ゲート（CI）**: GitHub Actions で全テスト・型・カバレッジ・契約テスト・gitleaks・npm audit を実行（正しさの最終判定）。
- **最終ゲート**: merge queue 導入時は必須 status check 通過まで自動マージ不可。

### 補足ルール
- 軽量トリアージ: lint + 型チェック + 影響範囲テストのみ実施し、限定版 GATE（型・テスト・lint）通過で COMMIT 可。
- TEST 範囲: #011/#057 は変更ファイルのみ。orchestrator は全件（プロジェクト全体の回帰確認）。
- UI変更 (#057) 後は `ドッグフーディングテスト`（実ブラウザでの目視確認）が必須。テスト成功のみでは完了としない。
- 既存壊れテスト: 変更起因 → 即修正。既存障害 → #081 が修正/削除判断。
- サブエージェント作業中に発見した副次的な問題は `## Drive-by Findings` 形式で報告。セッション終了時までに対応（修正 or 記録）。
- テスト失敗/未完了 → コミット禁止。
```

#### 4.4 .spec/ 4ファイル

コーディングや業務作業の前に必ず仕様を整理するための4ドキュメント。

**PLAN.md**（人間の口頭メモ・自由記述。エージェントが読んでヒアリングし SPEC.md を作成する）:

```markdown
# PLAN - やりたいこと

<!-- ここに思ったことを自由に書いてください。箇条書きでも口語でもOK -->
<!-- Claude がこの内容を読んでヒアリングし、SPEC.md を作成します -->
```

**SPEC.md**:

```markdown
# SPEC - 技術仕様・要件定義

## 機能要件
- [ ] 機能1：説明
- [ ] 機能2：説明

## 非機能要件
- パフォーマンス：
- セキュリティ：
- 制約条件：

## 技術構成
- 言語・フレームワーク：
- インフラ・環境：
- 外部サービス・API：

## データ構造・インターフェース
- 主要なデータ定義
```

**TODO.md**:

```markdown
# TODO - タスクリスト

## 優先度：高
- [ ] T001：タスク名（詳細）

## 優先度：中
- [ ] T002：タスク名（詳細）

## 優先度：低
- [ ] T003：タスク名（詳細）

## 完了済み
- [x] 初期セットアップ
```

**KNOWLEDGE.md**:

```markdown
# KNOWLEDGE - ドメイン知識・調査結果

## 業務・ドメイン知識
- この作業・プロジェクトに関する背景知識

## 調査・リサーチ結果
- 参考にした情報・ソース

## 技術的な知見
- 採用した技術の特性・注意点

## 決定事項と理由
- なぜこの方針にしたか（他の選択肢との比較）
```

#### 4.5 CLAUDE.md / GEMINI.md（プロジェクトルート）

```markdown
- セッション開始時に共通ルールである、AGENTS.mdを必ず読み込むこと。
- 読み込んだことを最初に報告すること
- 以下は <Claude Code|Gemini> 固有の差分のみ記載する
```

#### 4.6 .gitignore

```gitignore
# Logs
logs
*.log

node_modules
dist
dist-ssr
*.local

# Editor directories and files
.vscode/*
!.vscode/extensions.json
.idea
.DS_Store
.env
```

#### 4.7 Git初期化とpush

事前確認で取得した GitHub リポジトリ URL を使用する:

```bash
git init
git add .
git commit -m "first commit"
git remote add origin <REPOSITORY_URL>
git push -u origin main
```

### 5. 完了報告
以下を報告する:
- 記録した記憶の key・タグ
- 生成したファイル・フォルダの一覧
- GitHub への push 結果
- 次のステップの案内（「AGENTS.md にプロジェクト概要を記載してください」など）

## 制約
- `.agent/` ディレクトリや MEMORY.md / HANDOFF.md / `.agent/skills` / `.agent/workflows` / `.claude/commands/handoff.md` は**一切生成しない**
- AGENTS.md に「Memory & Handoff Instructions」節（MEMORY.md / HANDOFF.md の役割・読込ルール）は含めない。代わりに「Nous 記憶運用」節（上記 4.2）を提示する
- 記憶は必ず `project:<slug>` タグ付きで記録する（タグなしは分離できない）
