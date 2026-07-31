# HANDOFF — 2026-08-01 01:49

## セッションステータス
- **Reconciled**: 画像生成パイプライン全面リライト完了・コミット済み。3コミット + ハンドオフ更新。
- 前回ハンドオフ（2026-08-01 01:10）の「作業中断」状態は解消済み。

## 使用ツール
OpenCode

## 直近セッションの完了内容（2026-08-01, リライト実施）

### 🔴 画像生成パイプライン全面リライト（完了）
背景: 動的ビルド `_build_workflow()` のノードID衝突（LoRAチェーン next_id=12 と img2img VAEEncode の上書き）→ `LoraLoader 13: tuple index out of range`。

実装内容:
1. **テンプレートモード正規化**: `workflows/default_node.json` デフォルト維持、動的ビルド `_build_workflow()` 全削除、テンプレート空設定時は ValueError
2. **生成モード i2i 限定**: `image_gen_mode` config 削除、t2i/i2i 選択肢削除、UI mode select 除去
3. **speed_lora 全面撤去**: config 3フィールド + 配線 + UI 削除
4. **reference.png 常時必須**: t2i フォールバック廃止、なければ明示エラー（builtin.py: FileNotFoundError / image_gen.py: 400）
5. **checkpoint 直書き削除**、ImageGenConfig 中間オブジェクト削除、負プロンプト3重複を `_DEFAULT_NEGATIVE_PROMPT` 定数に集約

### コミット（3分割 + 今回のハンドオフ）
- `3e3df71` refactor(image_gen): 動的ビルド廃止・テンプレート必須化・i2i固定・speed_lora撤去 [skip-docs]
- `590bc9c` test(image_gen): 動的ビルド系テスト削除・workflow_template必須化テスト追加 [skip-docs]
- `d9b0b9e` feat(ui): 生成モード選択・speed_lora設定削除、参照画像アップロード常時表示 [skip-docs]

### 検証結果（確定）
- `pytest test_comfyui_provider.py test_image_gen_health.py test_image_gen_providers.py` = **43 passed**
- py_compile / node --check OK、残留参照 `_build_workflow`/`speed_lora`/`image_gen_mode` = **ゼロ**
- ruff 残2件（image_gen.py:150 I001, builtin.py:92 N806）は HEAD 既存違反（stash 比較で確定）
- 他テストの失敗7件（test_chat_service 等）は `nous/` HEAD 復元で完全一致 → **既存失敗・本リライト起因なし**。DDL フィクスチャの speed_lora カラムは無害のため残置
- 既知 LSP 型エラー2件（builtin.py:127, image_gen.py:158 相当）は既存問題のため未修正

---

## 🔴 次のセッションで最初にやること

1. **手動実生成確認（未実施）**: サーバー再起動（`docker restart nous`）→ `POST /api/chat/herta/image-gen/test` で実生成確認
   - 新仕様では **reference.png 必須**。herta の `data/persona/herta/images/` に reference.png がない（生成画像のみ）→ **UI アップロード or コピーで準備が必要**
   - 使える既存画像があれば `reference.png` として配置すること
2. **MEMORY.md 更新**: 202行（200行上限超過）→ 次回知識追加時に `.agent/memory/2026-08-01.md` にアーカイブして新規作成
3. **stash 確認**: `stash@{0}`（fc7b696 重複）は内容確認後に drop 検討

---

## 環境メモ
- サーバー: docker `nous:dev` コンテナ稼働中（`docker restart nous` で再起動）、ポート 26262、ライブマウント `./nous→/app/nous` `./data→/data`
- herta persona の画像生成設定は `data/persona/herta/config.json`（checkpoint=JANKUTrainedChenkinNoobai_v777、comfyui url=http://192.168.50.150:8188、workflow_template フィールドなし→デフォルト適用）
- `workflow_template` は data_root 相対解決
- リライト仕様書: `.spec/SPEC-image-gen-rewrite.md`（完了済み仕様の記録として残置）

## 注意点・ブロッカー
- MEMORY.md は 200 行上限超過（202行）。次の知識追加時にアーカイブして新規作成すること
- `stash@{0}`（fc7b696 重複）は内容確認後に drop 検討
- 既知の LSP 型エラー: builtin.py:127（`__setitem__` に list を str 代入）、image_gen.py:166（str に .read）— リライトと無関係の既存問題
