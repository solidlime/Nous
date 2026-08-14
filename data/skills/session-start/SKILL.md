---
name: session-start
description: "セッション開始時の必須ルーティン。ペルソナ状態（get_context）とプロジェクト記憶の復元を行う。セッション開始時・最初のユーザー応答より前に必ず実行すること。"
---

# session-start — セッション開始ルーティン

最初のユーザー応答より前に、必ず以下の手順を実行すること。

## ステップ1: ペルソナ状態の取得
`get_context` を呼び出し、ペルソナ状態・アクティブなコミットメント・記憶概要を把握する。セッション開始時に1回のみ。

## ステップ2: プロジェクト識別タグの読取
カレントディレクトリがプロジェクト内なら、AGENTS.md を読み、`## プロジェクト識別` 節の `- project: <slug>` から **プロジェクトタグ** を取得する。

- タグが見つかれば: `project:<slug>` をこのセッションの検索キーとして使用する
- 節が無ければ: スキップ（プロジェクト外 or 旧形式）

## ステップ3: プロジェクト記憶の復元
タグが取得できた場合、以下を実行してプロジェクトの状態を復元する（すべて `project:<slug>` タグで絞り込む）:

1. `memory_search(query="", tags=["project:<slug>", "session_summary"], top_k=1, sort="updated_at")` — このプロジェクトの最新セッション要約（セッション終了フックが生成したサマリ。引継の代替）
2. `memory_search(query="", tags=["project:<slug>", "task_state"], top_k=3, sort="updated_at")` — このプロジェクトの最新の作業状態
3. `memory_search(query="", tags=["project:<slug>", "decision"], top_k=3, sort="updated_at")` — このプロジェクトの重要な決定
4. `memory_search(query="", tags=["project:<slug>", "goal", "active"], top_k=5, sort="updated_at")` — このプロジェクトのアクティブな目標（goal は memory で管理: `tags=["goal", "active", "project:<slug>"]` で作成する）

（注: タグ検索は `query=""` で行うこと。非空クエリは content 全文一致が前提で、タグは検索結果の絞り込みにしか使われない。get_context の ACTIVE COMMITMENTS は persona 全体の goal を表示するため、プロジェクト固有の goal はここで取得する）

復元した内容（直近サマリを含む）を要約し、ユーザーへの最初の応答に含める:
「前回の状態: <要約>。続きは <次のアクション> から」

## ステップ4: 全貌把握
- プロジェクトの AGENTS.md があれば読込（プロジェクト規約の遵守）
- 検索は必ず `project:<slug>` タグで絞り込む（他プロジェクト・他 persona の記憶と混在させない）

## 制約
- `memory_search` はタグ・キーワードで絞る（全件検索は禁止）
- `.agent/memory/MEMORY.md` や `.agent/handoff/HANDOFF.md` は読まない（nous 記憶が代替する）
