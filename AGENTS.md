# Project guide line

## 1. プロジェクト概要
- 本プロジェクトのプラン作成、および回答は全て日本語で行います。

## 2. プロジェクト識別
- project: nous

# Nous 記憶運用（.agent/ は使わない）

## セッション開始時（必須）
セッション開始時、ユーザーへの最初の応答の前に session-start スキルを実行し、nous 記憶から状態を復元する：
- `get_context` でペルソナ状態・直近サマリを取得
- 本 AGENTS.md の `## プロジェクト識別` 節から `project: nous` タグを取得
- `memory_search(tags=["project:nous", "task_state"], top_k=3)` 等で作業状態を復元
- `memory_search(tags=["project:nous", "session_summary"], top_k=1, sort="updated_at")` で前回の内容を把握

## メモリ管理
- 重要情報・決定・作業完了は nous に記録。`project: nous` タグ必須
- 状態変化時は `update_context` → `memory_create` の順で永続化
- `.agent/memory/MEMORY.md` / `.agent/handoff/HANDOFF.md` は使用しない（nous 記憶が代替）
- ローカルの自動メモリ機能（~/.claude/ 配下）は使用しない

## ハンドオフ管理
- セッション終了時の session_summary 生成（終了フック）が引継を代替する
- 手動引継が必要な場合は `memory_create(tags=["project:nous", "task_state"])` で記録

## 仕様駆動開発（SDD）ルール
- コーディングや業務作業を開始する前に、必ず `.spec/` 配下の4ファイルを確認・更新すること
- 作業の順序：PLAN（目的確認）→ SPEC（要件確認）→ TODO（タスク確認）→ 実作業
- **PLAN.mdは人間の口頭メモ・自由記述**であり、箇条書き・口語・断片的な内容で構わない
- PLAN.mdを読んだら、そのまま実装に入らず、不明点をヒアリングしながらSPEC.mdを作成・確定させること
- SPEC.mdが確定してからTODO.mdのタスク分解を行い、ユーザーの承認を得てから実作業を開始する
- 作業完了後は TODO.md の該当タスクにチェックを入れ、KNOWLEDGE.md に学びを記録する
- 仕様が不明確な場合は作業を開始せず、ユーザーに確認してから SPEC.md を更新する

## ドキュメント更新ルール（必須）
- ドキュメント更新の基本ルールはグローバルプロンプトに従うこと
- 本プロジェクト固有のルール:
  - `nous/` 配下のコード（テスト・マイグレーション・`__init__.py` を除く）を変更した場合、`docs/` / `README.md` / `CLAUDE.md` のいずれかを更新、またはコミットメッセージに `[skip-docs]` を明示
  - MCP ツールの追加・変更・削除があった場合は必ず `docs/llm_usage_guide.md` を更新すること

## バックエンド変更→フロントエンド同期ルール（必須）
- バックエンド（API/MCP/domain）に変更を加えた場合、フロントエンド（`nous/api/http/static/` / `nous/api/http/sections/`）への反映要否を必ず確認すること
- 反映が必要な場合は TODO にタスクとして追加し、実装前にユーザーに確認する
- 反映漏れが発生した場合は MEMORY.md に記録し、再発防止策を検討する
