# PLAN: Nous 軽量化 + MCPハブ化

- compose から searxng, opensandbox, playwright を消す
- コードから searxng, opensandbox, playwright への依存を消す
- チャットUIの MCP サーバー登録機能は維持（むしろ強化）
- Dockerイメージを軽量化しつつ、MCPハブとして npx / npm / uv / python / git 等を同梱
- ユーザーが自由に MCP サーバーを登録して使える環境に
- /search ツールは完全削除
