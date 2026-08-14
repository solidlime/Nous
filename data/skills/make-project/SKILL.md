---
name: make-project
description: "新規開発プロジェクトの初期構築スキル。プロジェクトの識別タグ決定・初期記憶の記録・AGENTS.md 構成の提示を行う。『プロジェクトを初期化して』『プロジェクトをセットアップして』『新規プロジェクトを始めたい』などのリクエストで必ず使用すること。"
---

# make-project — プロジェクト初期構築

## 設計思想
- プロジェクトの記憶・引継は全て nous 記憶システムに記録する（`.agent/` 等のファイル運用はしない）
- プロジェクトは **`project:<slug>` タグ**で識別する。このタグが全記憶の共通キーになる
- ファイル生成（AGENTS.md・.spec/・git init）はユーザー側のエージェントが行う。このスキルは「記憶の初期化」と「生成すべきファイルの指示」を担う

## 手順

### 1. プロジェクト情報の確認
ユーザーに以下を確認する（曖昧なら推測して確認を取る）:
- **slug**: プロジェクト識別子（英数字・ハイフン。例: `nous-unification`）
- プロジェクトの目的・概要
- 技術構成・言語

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

### 4. AGENTS.md 構成の提示
ユーザー側のエージェントが生成すべき AGENTS.md の構成を出力する:

```markdown
# Project guide line

## 1. プロジェクト概要
- <概要>

## 2. プロジェクト識別
- project: <slug>
```

- `## プロジェクト識別` 節は**必ず含める**こと（session-start スキルがこの節からタグを読み取る）
- その他（SDD ルール・品質ゲート）はユーザー側エージェントの規約に従う

### 5. 完了報告
- 記録した記憶の key・タグ
- 生成すべきファイル一覧（AGENTS.md / .spec/ 4ファイル / README.md / git init）
- 次のアクション（ユーザー側エージェントの作業開始）

## 制約
- `.agent/` ディレクトリや MEMORY.md / HANDOFF.md は生成しない
- 記憶は必ず `project:<slug>` タグ付きで記録する（タグなしは分離できない）
