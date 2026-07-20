# TODO — 全タスク統合リスト

## 完了済み

### sentence-transformers → ONNX Runtime
- [x] T001-T005: Phase 0 事前検証（ONNXモデル入出力確認、ST出力比較、torch grep）
- [x] T006-T011: EmbeddingModel ONNX化（model.py 全メソッド）
- [x] T012-T014: RerankerModel ONNX化（reranker.py 全メソッド）
- [x] T015-T018: 設定・環境変数・依存関係更新（settings, main, requirements）
- [x] T019-T023: テスト更新 + スキップ7件解消（zipデータ不在テスト削除）
- [x] T024-T027: 全テスト実行 + ドキュメント + コミット
- [x] T028: Dockerfile から torch 明示的インストール削除

### mcp-hub
- [x] T101: mcp-hub/Dockerfile マルチステージビルド化

---

## 優先度：高（リファクタリング）

- [x] R1: reranker.py スレッド安全性修正 — `_ensure_loaded()` パターン追加（`rerank()` の lazy-load に二重チェックロッキングがないバグを修正）
- [x] R2: デッドコード削除
  - `_get_session_options()` (model.py:258-262) — インライン化済みで未使用
  - `get_status()` (model.py:193-199, reranker.py:175-182) — 呼び出し元ゼロ
  - `encode_batch()` の `batch_size` パラメータ — 未使用
  - **R2+**: settings/runtime_config/settings.js の孤児化 batch_size 設定も完全除去
- [x] R3: CI グリーン化 — `use_cases.py` のバックグラウンドスレッド化変更 + テスト修正をコミット
  - 合わせて persona.py のセットアップ画面に AbortController+60sタイムアウト追加

## 優先度：中

- [x] R4: Dockerfile から `build-essential` 削除（全依存が pre-built wheel、不要）
- [x] R5: `_init_vector_store` の `ThreadPoolExecutor(asyncio.run())` 二重ネスト簡素化

## 優先度：低

- [x] R6: `TestAppContextRerankerInstantiation` のテスト fixture 化
- [x] R7: BaseONNXModel 導入の是非を再検討 → 条件不成立のためスキップ（3つ目のONNXモデル未登場）

## 別タスク枠

- [x] T029: Docker イメージビルド検証 → 最終イメージ1.08GB、ビルド成功確認済み
- [x] T102-104: mcp-hub CI 確認（docker-compose 正常） + requirements-dev.txt 整理 + CI改善（torch除去・SHAピン留め・timeout追加）

### チャット編集・削除・再生成
- [x] T105: chat-history.js — 編集後の自動再生成（後続メッセージがある場合のみ）
- [x] T106: chat-history.js — deleteChatMessage() 追加（確認ダイアログ+ロールバック+直前メッセージで再生成）
- [x] T107: chat-send.js — ユーザーメッセージに削除ボタン追加
- [x] T108: chat.css — 削除ボタンホバー色（accent-red）

### Apple HIG リデザイン
- [x] T201: base.css — CSS変数体系をApple HIG準拠に全置換（カラーパレット、スペーシング、角丸、シャドウ）
- [x] T202: base.css — 全コンポーネント（ボタン、カード、入力欄、モーダル、トースト等）のスタイルをApple風に刷新
- [x] T203: chat.css — チャットUIをiMessage風に変更（吹き出し、タイピングインジケーター、入力欄）
- [x] T204: base.css — ダーク・ライト両モードのCSS変数セット作成
- [x] T205: base.py — headセクションにInterフォントの読み込みを追加
- [x] T206: レイアウトやレスポンシブの微調整
- [x] T207: アクセシビリティ（WCAG 2.1 AA）の確認

### Minimal B: parentIdツリー構造移行（チャット編集・削除リライト）
- [ ] T301: session_store.py — TreeSessionWindow コア実装（add/edit/delete/rollback/get_active_path/persist/from_db）
- [ ] T302: session_store.py — SessionManager 更新（TreeSessionWindow対応 + get_messages ID追加）
- [ ] T303: events.py — DoneSSE に user_msg_id/assistant_msg_id 追加
- [ ] T304: context.py — ChatTurnContext に user_msg_id/assistant_msg_id 追加
- [ ] T305: service.py — session.add() 戻り値活用 + turn_ctx 保存
- [ ] T306: post.py — DoneSSE に message_id 渡し
- [ ] T307: chat.py — PUT /messages/{msg_id} 更新（index→ID）
- [ ] T308: chat.py — POST /rollback 更新（keep_until→from_id）
- [ ] T309: chat-send.js — appendChatMessage/_createAssistantDiv に data-msg-id
- [ ] T310: chat-send.js — done イベントで msg_id を DOM に設定
- [ ] T311: chat-history.js — editChatMessage IDベース
- [ ] T312: chat-history.js — rollbackChat IDベース + DOM再構築
- [ ] T313: chat-history.js — deleteChatMessage IDベース
- [ ] T314: chat-history.js — restoreChatHistory data-msg-id 設定
- [ ] T315: test_chat_service.py — TreeSessionWindow テスト群
- [ ] T316: test_chat_service.py — 既存テスト TreeSessionWindow 移行
- [ ] T317: 統合テスト実行 + 手動確認 + 旧SessionWindowクリーンアップ
