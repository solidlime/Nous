# sandbox を既定のシェルにする / 承認の自動化

2026-11-17。ユーザー要望（原文）:
「承認するしないがでないんだけど。あと自動承認のオンオフ設定も欲しいな。sandboxツール叩かないでも
自動でsandbox操作するようにして欲しい。コマンドは何でも実行できるような感じ」

## 決定

### 1. 承認ダイアログが出ない件

`nous/api/http/static/chat/send/turn.js:176` の
`if (evt.type === "approval_requested") { if (!_hubSkipMode) _askApproval(evt); return; }`
が、`_hubSkipMode`（接続直後のリングバッファ再生を飲むためのフラグ）が立っている間だけ
ダイアログを落とす。`_hubSkipMode` は `onOpen`（アイドル時）で true、`_beginTurnSession` と
終端イベントで false になるが、**ライブのターン中に来た承認は `_turn` が居るため
終端イベント側の解除枝に入らず**、再生ウィンドウが閉じないケースがある。

修正: 承認は「解決済みなら POST が no-op で返る」ので、`_hubSkipMode` では落とさない。
代わりに**承認 ID の重複だけ**を弾く（`_askedApprovals` の Set、上限 32）。

### 2. 自動承認のトグル

`ChatConfig.shell_approval_mode`（ask / allowlist / auto）は既にあるが UI が無い。
チャット設定の tools セクションにトグル「ツール実行を自動承認」を足し、
on → `shell_approval_mode: "auto"` / off → `"ask"`。

### 3. sandbox を既定のシェルに

`sandbox_enabled` かつ `sandbox_manager_url` があるとき、ワークスペースツール
（`bash` / `read_file` / `write_file` / `edit_file`）を **sandbox コンテナ内で実行**する。
`workspace_root` は不要。別ツール `sandbox` は一覧から外す（`bash` に統合）。

実装（nous 側で完結させる。イメージは ubuntu:24.04 で python3 が無い前提）:
- `bash` → manager `/exec`（cwd 既定 `/home/<persona>/workspace`）。**任意コマンド**。
- `read_file` → `base64 -w0 < path` を実行して nous 側でデコード。
- `write_file` → 本文を base64 にして `printf %s <b64> | base64 -d > path`。
- `edit_file` → read と同じ経路で読む → nous 側で exact-match 置換 → write と同じ経路で書く
  （コンテナに python/perl を要求しないため）。

パス規約: 相対パスは workspace 起点。`..` で workspace の外へ出るのは許可する
（sandbox は使い捨てで、ホストの他ペルソナ領域はマウントされていない）。

## 触らない

- `nous/services/sandbox_manager.py`（動いている。契約は変えない）
- `approval.py` のモード意味論（auto/allowlist/ask の解釈は 1 箇所のまま）
- `workspace_root` 経路（sandbox 無効時は今のまま）
