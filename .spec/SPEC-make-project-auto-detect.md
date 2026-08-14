# SPEC - make-project 自動検出拡張

- 日付: 2026-08-14
- 状態: 設計確定（実装は未実施・計画のみ）
- 関連: make-project / session-start / SPEC-nous-unification.md

## 背景

新規プロジェクトで「明らかにコーディングプロジェクト」と判断できる場合に、
AGENTS.md の自動生成とプロジェクトタグ（`project:<slug>`）の自動付与を行いたい。

現状:
- make-project はユーザーが明示的に初期化を依頼したときだけ動く（手動トリガー）
- session-start はタグ読取・記憶復元のみ（生成機能なし）
- nous アプリ自体は不変更方針（配布は chezmoi externals 経由のスキルファイルのみ）

## 方針（ユーザーとの合意事項）

1. **トリガー**: セッション開始時ではなく、コーディング開始・初期化リクエスト検知時に make-project を起動。session-start は現状維持。
2. **判定**: 機械的条件式ではなく LLM（エージェント）がファイル状態を見て判断。
3. **確認**: 生成前に常にユーザー承認を得る。黙って生成しない。
4. **生成物**: AGENTS.md + `project:<slug>` タグ付き初期記憶（従来の make-project 生成物と同じ）。
5. **スコープ**: make-project スキルのみ変更。session-start / nous アプリ / プラグインは変更しない。

## 機能要件

### F1: プロジェクト判定（新ステップ）
コーディング開始 or 初期化リクエスト時に、カレントディレクトリを検査:

| ディレクトリ状態 | 判定 | 動作 |
|---|---|---|
| 空 / 設定ファイルのみ（.vscode 等） | 通常会話 | スキップ（生成しない） |
| コード・言語マニフェストあり（package.json / pyproject.toml / src/ / *.ts 等） | 明らかにコーディング | ユーザーに確認してから生成 |
| 状態が不明 | 不明 | ユーザーに質問して判断 |

判定は LLM がファイル一覧を見て行う。機械的な条件式・ルールファイルは持たない。

### F2: 確認フロー（常時）
- AGENTS.md なし → 「AGENTS.md を生成して `project:<slug>` タグを付けますか？」と提案 → 承認で生成
- AGENTS.md あり → 「`project:<slug>` タグを付けますか？」と提案（タグ付けのみ。AGENTS.md は触らない）
- 拒否 → 何も生成せず通常の会話を継続
- 不明 → 質問してから判断（質問1つのみで絞り込む）

### F3: 既存 AGENTS.md 保護
- 既に AGENTS.md が存在する → 生成しない（上書き禁止）
- 既存 AGENTS.md がある場合でも**タグ付けのみは提案する**。slug は AGENTS.md の `## プロジェクト識別` 節から読み取る（節がなければユーザーに確認）

### F4: タグ付け
- 生成時、既存フローどおり `memory_create(tags=["project:<slug>", "project_overview"], importance=0.8, kind="semantic")`
- slug 衝突時（memory_search で同名検出）→ 別 slug を提案（既存の重複確認を流用）

### F5: 既存機能との統合
- 事前確認（slug・概要・技術構成・GitHub URL）は既存ステップを流用
- README / .spec/ / CLAUDE.md / GEMINI.md / .gitignore / git init は従来どおり（自動検出経由でも、ユーザーが希望すれば従来フローを継続可能）

## 非機能要件

- **配布**: `~/.agents/skills/make-project/SKILL.md` と `data/skills/make-project/` を同期更新（chezmoi externals 配布）
- **互換性**: session-start は変更しないため、既存セッションの復元動作に影響なし
- **日本語**: プロジェクト生成物・プロンプトは日本語のまま

## 変更ファイル

| ファイル | 変更内容 |
|---|---|
| `data/skills/make-project/SKILL.md` | 「プロジェクト判定」ステップ追加、確認フロー明記 |
| `~/.agents/skills/make-project/SKILL.md` | 同上（chezmoi 同期） |

## テスト計画

スキルは指示書のためユニットテストなし。実地検証 3 ケース:

1. **空ディレクトリ**: 通常会話としてスキップされること
2. **コードあり**: 検出 → ユーザー確認 → 承認で AGENTS.md 生成 + タグ付き記憶が記録されること
3. **不明**: ユーザー質問が発生し、回答後に正しく判断されること

検証は次セッション以降の実セッションで実施。

## 非スコープ

- session-start への検出ロジック追加（しない）
- opencode プラグイン / nous アプリの変更（しない）
- 機械的な検出ルールファイル（持たない）
