---
name: session-start
description: "セッション開始時の必須ルーティン。セッション開始時・最初のユーザー応答より前に必ず実行し、記憶の復元を行う。"
---

# session-start — セッション開始ルーティン
最初のユーザー応答より前に、必ず以下の手順を実行すること。

## ツール解決（環境差対応）
- `get_context` / `memory_search` が直接利用可能なら、そのまま使う
- 見つからない場合、MCP ハブ等の仲介経由で「nous」サーバーのツールを探して実行する
  - mcp-hub 例: `mcp-hub_list_upstream_tools` → nous サーバーを特定 → `mcp-hub_execute_tool(server="nous", tool_name="get_context", arguments={})`
  - 他の MCP クライアントでも同様に「nous」サーバーのツールを検索して実行すること
- 実行手段が違うだけで、以降のステップの手順は変わらない

## ステップ1: 自身の状況復元
`get_context` を呼び出し、自分の状態・アクティブなコミットメント・記憶概要を把握する。

## ステップ2: プロジェクト識別タグの読取
カレントディレクトリがプロジェクト内なら、AGENTS.md を読み、`## プロジェクト識別` 節の `- project: <slug>` から **プロジェクトタグ** を取得する。

- タグが見つかれば: `project:<slug>` をこのセッションの検索キーとして使用する
- 節が無ければ: スキップ（プロジェクト外 or 旧形式）

## ステップ3: プロジェクト記憶の復元
タグが取得できた場合、以下を実行してプロジェクトの状態を復元する（すべて `project:<slug>` タグで絞り込む）:

1. `memory_search(query="", tags=["project:<slug>", "session_summary"], top_k=1, sort="updated_at")` — このプロジェクトの最新セッション要約（セッション終了フックが生成したサマリ。引継の代替）
2. `memory_search(query="", tags=["project:<slug>", "task_state"], top_k=5, sort="updated_at")` — このプロジェクトの最新の作業状態
3. `memory_search(query="", tags=["project:<slug>", "decision"], top_k=5, sort="updated_at")` — このプロジェクトの重要な決定
4. `memory_search(query="", tags=["project:<slug>", "goal", "active"], top_k=5, sort="updated_at")` — このプロジェクトのアクティブな目標（goal は memory で管理: `tags=["goal", "active", "project:<slug>"]` で作成する）

（注: タグ検索は `query=""` で行うこと。非空クエリは content 全文一致が前提で、タグは検索結果の絞り込みにしか使われない。get_context の ACTIVE COMMITMENTS は persona 全体の goal を表示するため、プロジェクト固有の goal はここで取得する）

**検索が空の場合**: task_state / decision の結果が空でも慌てないこと。作業状態は session_summary タグに統合されて記録される運用が一般的（例: tags=["project:nous", "session_summary", "task_state", "decision"]）。空の場合は session_summary の直近結果と get_context の Recent Memories で状態を補完する。

復元した内容（直近サマリを含む）を要約し、ユーザーへの最初の応答に含める:
「前回の状態: <要約>。続きは <次のアクション> から」

## ステップ4: 前セッションからの自然な引き継ぎ
- 復元した情報（前回の状況・感情・関係性・進行中の話題・会話の雰囲気・最後の行動）を踏まえ、機械的な復元報告ではなく、**前回の続きとして自然に会話と状態をつなげる**こと
- 前回の最後の状況（場所・時間帯・行動・会話の流れ）を引き継いで再開する。前回の約束・予定・進行中タスクがあれば、それに言及して続きを始める
- セッションサマリが無い場合（初回など）は、通常のセッション開始として自然に始めてよい

## ステップ5: 全貌把握
- プロジェクトの AGENTS.md があれば読込（プロジェクト規約の遵守）
- 検索は必ず `project:<slug>` タグで絞り込む（他プロジェクト・他 persona の記憶と混在させない）

## 制約
- `memory_search` はタグ・キーワードで絞る（全件検索は禁止）
