# アイドル時好奇心探索（内省フロー織り込み）設計

- 日付: 2026-09-10
- 状態: 承認済み（ユーザー承認）
- スコープ: 会話していない時間帯の自発的内省に、好奇心駆動の MCP ツール探索を織り込む

## 背景

ユーザー要望: 「会話してないときに自動で情報収集してくれると最高」。その後の対話で方針が以下のように確定:
- 情報収集は「内省中に気になったことを自分で調べる」流れとして実装する（独立ワーカー案は不採用）
- web 検索プロバイダをハードコードしない。**登録済みの MCP ツールを自動判断で使う**（ユーザー明示指示）

既存調査の結果、内部側は既存システムで被覆済み:
- `EnrichmentWorker._maybe_spontaneous`（nous/application/workers/enrichment_worker.py:150-163）— アイドル ≥ `brain_idle_after_seconds`（120s）で `run_spontaneous` 発火
- `run_spontaneous`（nous/application/chat/introspection.py:557）— `_SPONTANEOUS_PROMPT`（introspection.py:79）で独り言・感情・memories を JSON 産出
- `ReflectionEngine` / `ConsolidationWorker` — 洞察の記憶化・gist 統合

探索に使う既存機構:
- `MCPClientPool.list_all_tools()`（nous/infrastructure/mcp_client/pool.py:44）— 接続済みサーバーの全 MCP ツールを ToolDefinition（name/description/input_schema）で返す
- `MCPClientPool.call_tool`（nous/infrastructure/mcp_client/pool.py:57）— `{server_name}__{tool_name}` でルーティング、タイムアウト 30s

**訂正（実装計画時に発見）**: 当初案の `ToolSearchEngine` は使わない。`ToolDefinition.defer_loading` のデフォルトは False（nous/infrastructure/llm/base.py:28）で、MCP ツール生成時に指定されないため **MCP ツールは Qdrant の tool_definitions コレクションに索引されない**（`_ensure_tool_index` は deferred ツールのみ索引、nous/application/chat/service.py:69）。代わりに `pool.list_all_tools()` の一覧をそのまま選択プロンプトに載せる（ツール数は数十程度で、候補絞り込み＋引数生成が同一 LLM 呼出で済む。Qdrant/embedding 依存も消える）。無効ツールの除外は `config.disabled_tools`（nous/domain/tool_config.py:17）。

## 設計

### 1. プロンプト拡張

`_SPONTANEOUS_PROMPT` に出力フィールドを1個追加:

```
"curiosity": "この静かな時間に気になって調べたいこと（一人称・なければ null）"
```

ペルソナの一人称で疑問を書かせる。既存フィールド（monologue/violation/emotion/body_state/memories）は変更しない。後方互換: 既存 LLM 応答に curiosity が無くても動く（optional 取扱い）。

### 2. 好奇心探索ステップ（run_spontaneous 内・逐次）

`generate` 成功後、以下の条件を満たすとき実行:
- `result.curiosity` が非null
- `explorer.enabled` が true（settings）

実行内容:
1. `MCPClientPool(config.mcp_servers)` を `async with` で開き、`pool.list_all_tools()` から無効ツール（`config.disabled_tools`）を除外した候補一覧を取得。空ならスキップ
2. LLM 1回: 候補一覧（name/description/input_schema）＋curiosity を渡し、`{"tool_name": "...", "args": {...}}` または `null`（適合ツールなし）を判定させる — これが「MCP ツールの自動判断」。`tool_name` は候補一覧に存在する名前に限定（ハルシネーション排除）
3. `null` でなければ `MCPClientPool.call_tool(tool_name, args)` を実行（≤ `explorer.max_tool_calls` 回、デフォルト1）。エラー応答（`error` キー or `isError`）なら要約・記憶に進まず静かに終了
4. 結果を LLM 1回で一人称・独り言調に要約
5. 要約を `memory_create`（semantic、tags に `exploration`、importance 0.4）
6. 既存 emit 経路で、独り言本体の後に**別バブル**として発行（`brain_monologue_enabled` 尊重）——「気になった→調べた→ぽつり」の連なりで見える

探索が失敗（ネットワークエラー・タイムアウト・エラー応答）しても独り言本体は既に発行済みなので、探索部分は静かにスキップ。worker は止めない（既存の全段 try/except 慣習どおり）。

### 3. コスト上限（ハードcap）

1回の自発内省あたり:
- 独り言生成 LLM 1回（既存）
- ツール選択 LLM ≤1回
- MCP ツール呼出 ≤1回（`explorer.max_tool_calls`、デフォルト1）
- 要約 LLM ≤1回

`explorer.enabled=false`（デフォルト）のときは既存の自発内省とコスト完全同一。

### 4. 設定

`settings.py` に `ExplorerConfig` 追加（2キー）:
- `enabled: bool = False`
- `max_tool_calls: int = 1`

yaml で上書き可能。

### 5. スコープ外

- 会話駆動の `run_introspection`（introspection.py:494）には好奇心探索を付けない。ターン毎発火で頻度が高くコストが読めないため。将来同じ拡張を転用可。
- 検索結果の記憶化における重複排除は既存の `memory_create` 側機構に任せる（新機構を作らない）。
- 検索プロバイダの実装・追加はしない。使えるかどうかは登録済み MCP ツール次第。

### 6. テスト

- `curiosity=null` のとき探索ステップが走らない
- `explorer.enabled=false` のとき走らない
- ツール候補0件または LLM 判断が `null` のとき静かにスキップ
- 無効ツール（disabledTools）が候補から除外される
- 正常系: 判断→call_tool→要約→記憶保存→emit まで
- call_tool 失敗時に独り言本体の emit が壊れない
- fake ToolSearchEngine / fake pool / fake LLM を使用。実 MCP サーバーに触れない

### 変更対象ファイル（想定）

- `nous/application/chat/introspection.py` — プロンプト拡張 + 好奇心探索ステップ
- `nous/infrastructure/settings.py` — `ExplorerConfig`
- `tests/unit/test_introspection.py` — 上記テスト
