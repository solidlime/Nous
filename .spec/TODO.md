# TODO: ブラウザ・サンドボックス外部MCP移行 + WebUIバグ修正

（@oracle v2 レビュー（全指摘解決） + v3 追補修正済み）

- [ ] **Chunk 1**: Dockerインフラ（sandbox削除 + Playwright MCP + OpenSandbox Server + MCP）
- [ ] **Chunk 2**: バックエンド — ブラウザコード削除
- [ ] **Chunk 3**: バックエンド — サンドボックスコード削除（chat_config 7箇所 + REST API 8endpoint + attachment_uploadリネーム + tools/__init__.py）
- [ ] **Chunk 4**: 外部MCPサーバー設定追加
- [ ] **Chunk 5**: WebUI更新（JS/HTML sandbox全参照削除 + TTS修正 + 設定保存修正 + デッドコード）
- [ ] **Chunk 6**: テスト修正
- [ ] **Chunk 7**: ドキュメント更新 + 最終検証 + CI確認
