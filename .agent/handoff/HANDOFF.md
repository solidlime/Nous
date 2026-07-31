# HANDOFF — 2026-08-01 00:17 (Session Reconciled)

## セッションステータス
- **Reconciled**: セッションの成果は全てコミット済み・push済み。未コミット作業なし。
- `git status` clean / `main` = `origin/main`（0 ahead / 0 behind）
- 前回ハンドオフ（2026-07-26 Phase 12）以降の作業を統合した記録に更新。

## 使用ツール
OpenCode

## 直近セッションの完了内容（2026-07-25〜08-01, 50 commits, all on main）

### ComfyUI 画像生成（最大のテーマ群）
- `image_gen_mode` (t2i/i2i) 追加、i2i 参照画像アップロード UI + テストエンドポイント対応
- サイズ指定を名前付きプリセットシステムに置換（`52c836d`）
- ワークフローテンプレートモード追加（IP-Adapter は追加→削除で revert、`60106ea`）
- `NOUS` タグ注入・`NOUS:display` ノードフィルタ・定数ノード対応・Power Lora Loader オブジェクト形式修正
- 生成画像に node id/title 付与、sampler/scheduler オプション拡充

### Overview / メモリダッシュボード UI
- ゲーム風ステータス画面（portrait hero + コンパクト）へ再設計
- タブ型 persona status panel（Main/Equipment/Goals）、Profile/Emotion/Equipment/Body カード統合
- メモリダッシュボード統計・ブロック・チャート表示（memories tab へ移設）
- 生成画像にプロンプトメタデータ付与、DOMPurify onclick/onchange 許可

### タイムコンテキスト & 応答検証
- `_build_time_context` を `<time_context>` タグでラップ + anti-echo 指示（`191704b`）
- タイムスタンプエコー・XML タグリーク検出を応答検証に追加
- `show_message_timestamps` config ガード、HTML コメント埋め込みで echo 防止
- プロンプト注入検知の suspicious unicode 範囲拡張

### TTS (irodori)
- LLM キャプション生成（`irodori_caption_llm_enabled/model` config、UI、感情強度計算修正）
- TTS 入力から `<time_context>` タグ・`msg_at` コメント除去

### その他
- `update_context` に `appearance` フィールド追加
- スキル指示を命令形に変更（polite tone 除去）
- README 簡素化、技術詳細は architecture doc へ移設

## 試したこと・結果
- ✅ 全変更を従来型コミット（feat:/fix:/refactor:/test:/docs:）でアトミックに分割、50 commits 全て main に統合
- ✅ 検証: `git status` clean、`origin/main` と同期、stash 1件のみ残存（`stash@{0}` fc7b696 — 既に main に存在するコミットの重複。次のセッションで drop 検討）

## 次のセッションで最初にやること
1. 現行 HEAD のコミットログを確認し、開発の起点を把握する
2. `.spec/PLAN.md` の進行中タスクと突き合わせて優先順位を再確認
3. `stash@{0}`（fc7b696 重複）は内容確認後に `git stash drop` する

## 注意点・ブロッカー
- 前回ハンドオフの制約（base.js / base.py の `window.*` アダプター、`__INITIAL_PERSONA__`）は Phase 13 で除去済みのため無効。残る `window.S` / `window.Nous.Core` destructure は安全な参照。
- MEMORY.md は 200 行上限に近い（202行）。次の知識追加時はアーカイブして新規作成すること。
