# カード #51 — エージェント→ユーザーへのファイル添付

## 現状
ユーザー→エージェントの添付は実装済み（`POST /api/chat/{persona}/attachment/upload` +
`GET /api/chat/{persona}/attachment/{filename}` + `chat-attachments.js` のバッジ）。
逆向き（エージェントが作ったファイルをユーザーに渡す）経路が無い。エージェントが
`write_file` / `bash` で作ったファイルはワークスペースに残るだけで、チャットからは
開けない（ワークスペースはホストのディレクトリで WebUI から辿る手段が無い）。

## 方針
**置き場をユーザー添付と同じ `persona/{persona}/uploads` にする。** 既存の配信ルート
（`attachment_serve`）と `sanitize`（basename + `..` 除去）がそのまま効き、新しい
ルート・新しい濫用面を増やさない。

| ファイル | 変更 |
|---|---|
| `nous/application/chat/tools/attachments.py` (新規) | `_handle_attach_file(ctx, config, tool_input)`。`path` をワークスペース相対（sandbox 稼働時はコンテナ内 `/home/agent/workspace` 起点）で解決し、uploads にコピーして `{"status":"ok","attachments":[{filename,url,mime_type,size,caption}]}` を返す。10MB 上限（WebUI の `MAX_ATTACHMENT_BYTES` と揃える）。同名は `_1` 連番。 |
| `nous/application/chat/tools/definitions.py` | `WORKSPACE_TOOLS` に `attach_file` を追加（workspace が使える時だけ出る＝作成手段が無い時に添付ツールだけ露出しない）。 |
| `nous/application/chat/tools/builtin.py` | `_BUILTIN_DISPATCH["attach_file"]`。`_WORKSPACE_TOOL_NAMES` には入れない（sandbox 分岐をハンドラ内で持つため二重実行になる）。 |
| `nous/application/chat/events.py` | `AttachmentSSE`（type `file_attach`、`attachments` + `tool_use_id`）。 |
| `nous/application/chat/pipeline/inference.py` | `_handle_tool_results` が `tool_result["attachments"]` を見て `AttachmentSSE` を積む（base64 が無いので `result_raw` はそのまま保存＝履歴復元で使える）。型注釈 union に追記。 |
| `nous/api/http/static/chat/chat-attachments.js` | `renderChips(list, container)` を公開（live と履歴で同一マークアップ）。 |
| `nous/api/http/static/chat/chat-tools.js` | `showFileAttach(evt)` = `data-tool-id` のツールバブル直後にチップを差す（`image_gen_result` と同じ位置規約）。ラベル/アイコン追加。 |
| `nous/api/http/static/chat/send/turn-events.js` | `evt.type === "file_attach"` → `showFileAttach`。 |
| `nous/api/http/static/chat/history/render.js` | `tool_result` 分岐で `tc.result_raw.attachments` があれば `renderChips`。 |
| `nous/api/http/static/styles/chat.css` | `.chat-file-attach`（チップ）と `.chat-file-list`。 |
| `docs/architecture.md` | ワークスペースツールの項に `attach_file` の 1 文。 |
| `tests/parity/test_tool_contract_registry.py` | `attach_file` を `_CONDITIONAL_TOOLS` に追加（workspace 依存＝設定次第で消えるため HTTP 面の契約に載らない）。 |

### 判断
- **承認は不要**（`approval.APPROVAL_REQUIRED_TOOLS` に入れない）: 既にエージェントが
  作った/読めるファイルを、ペルソナ自身の uploads に複製するだけで、新しい読み取り境界を
  越えない。`write_file` で作った物を渡すのに 2 度目の承認を求めない。
- **sandbox 稼働時はコンテナ内で `cp`**: manager は `persona/{persona}/uploads` を
  `/home/agent/uploads` に rw マウントしている（`nous/services/sandbox_manager.py:_mount_specs`）。
  ホスト側から見た sandbox のファイルは存在しないので、コピーはコンテナ内で行う。
  サイズ検査は cp 後にホスト側の実ファイルで行い、超過なら消してエラー。
- 送信元はワークスペース配下に限る（`resolve_in_workspace`）。artifacts
  (`persona/{persona}/artifacts/...`) は対象外 — 必要になったら足す。

## テスト
- `tests/unit/test_attach_file.py`: 正常コピー（name 上書き・連番）、ワークスペース外の
  拒否、存在しないパス、10MB 超過、sandbox 経路（manager をモック）。
- `pytest tests/unit tests/integration tests/parity` / `ruff` / `mypy` / `vitest run`。
- 実ブラウザ: ローカル起動した nous で `file_attach` の描画（live/履歴）を目視。
