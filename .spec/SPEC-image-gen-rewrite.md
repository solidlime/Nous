# 画像生成パイプライン リライト仕様

> 作成日: 2026-08-01
> 前提: ユーザー方針確定済み（動的ビルド廃止 / i2i限定 / speed_lora撤去 / テンプレート必須）

---

## 背景と動機

### 現状の問題
1. **動的ビルドのノードID衝突（🔴）**: `_build_workflow()` でLoRAチェーンが `next_id=12` から採番する一方、img2img時は `nodes["12"]=VAEEncode` が最初のLoRAを上書き → ComfyUIで `LoraLoader 13: tuple index out of range`。これがユーザー遭遇エラーの根本原因。
2. **CLIP配線非対称（🔴）**: 動的ビルドはCLIPTextEncodeがチェックポイント直結 `["4",1]` → LoRAのCLIP側が無視される。テンプレートは正しくPower Lora LoaderのCLIPを参照。
3. **二重実装**: テンプレートモードと動的ビルドの2経路が並存し、挙動が食い違う。
4. **speed_loraの黙った上書き（🟡）**: デフォルト非空 `lcm_lora_sdxl.safetensors` が動的モードのsampler/cfgを無条件上書き。UIでは `display:none` で隠蔽済み。
5. **デッドコード**: `factory.py`（呼び出しゼロ）、`ImageGenConfig` 中間オブジェクト、`reference_image_enabled` 未使用。

### ユーザー方針（確定）
- テンプレートモードを正規に維持（デフォルト `workflows/default_node.json` 添付のまま）
- **動的ビルド（`_build_workflow`）は廃止**
- **生成モードは i2i 限定**（t2i/i2i選択肢削除）
- **speed_lora は撤去**（設定・UI・オーバーライドロジック）

---

## 変更仕様

### 1. `nous/infrastructure/image_gen/comfyui.py`

| 変更 | 内容 |
|---|---|
| `__init__` | `speed_lora_path/weight/method` パラメータ削除。`workflow_template` を必須化（空なら ValueError） |
| `generate()` | 動的ビルド分岐削除。`workflow_template` 解決 → json.loads → NOUS注入のみ |
| `_build_workflow()` | **全削除**（L492-650 相当） |
| speed_lora オーバーライド | 削除（L508-528 相当） |
| img2img latent 配線 | テンプレート任せ（動的コードに存在した node11/12 構成は不要になる） |
| ハードコード負プロンプト | `"lowres, bad anatomy, bad hands, text, error"` の3重複を1箇所定数に集約 |

### 2. `nous/domain/tool_config.py`

| 変更 | 内容 |
|---|---|
| `image_gen_mode` | 削除（t2i/i2i選択肢廃止） |
| `image_gen_comfyui_speed_lora_path` | 削除 |
| `image_gen_comfyui_speed_lora_weight` | 削除 |
| `image_gen_comfyui_speed_lora_method` | 削除 |
| `image_gen_comfyui_workflow_template` | デフォルト `"workflows/default_node.json"` のまま維持（必須化の実装はcomfyui.py側） |

### 3. `nous/application/chat/tools/builtin.py`

| 変更 | 内容 |
|---|---|
| `_handle_image_generate()` | mode分岐削除（i2i固定）。speed_lora配線削除。参照画像 `reference.png` を常に読込、なければ明示エラー（t2iフォールバック廃止） |
| ハードコードcheckpoint | `noobaiXLNAIXL_...` 直書きを削除 → config値のみ使用 |
| `ImageGenConfig` 中間オブジェクト | 削除 or 有効活用 |

### 4. `nous/api/http/routers/image_gen.py`

| 変更 | 内容 |
|---|---|
| `test_image_gen()` | mode分岐・speed_lora削除。参照画像は常時読込（なければエラー） |
| ハードコードcheckpoint | 削除 → config値のみ |

### 5. UI (`chat_sidebar_media.py` / `chat-settings.js` / `chat-settings-image.js`)

| 変更 | 内容 |
|---|---|
| mode select（t2i/i2i） | 削除 |
| speed_lora UI（display:none） | 削除 |
| 参照画像アップロードUI | i2i固定なので常時表示に変更 |
| テストボタン | そのまま（テストAPIもi2i固定） |

### 6. テスト (`tests/unit/test_comfyui_provider.py`)

- `_build_workflow` 系テスト（動的ビルド）を削除・整理
- テンプレートモード必須の検証テスト追加（workflow_template空→ValueError）
- 既存テンプレート注入・NOUSタグ・Power Lora形式テストは維持

---

## 検証計画

1. `pytest tests/unit/test_comfyui_provider.py -q` — 全パス
2. `python3 -m py_compile` 対象ファイル
3. `ruff check` 変更ファイル
4. 手動: サーバー再起動 → `/api/chat/herta/image-gen/test` で実生成確認（参照画像ありのi2i）

## コミット方針

- 破壊的変更のため複数コミットで分割可能（comfyui.py / config / builtin+router / UI / テスト）
- docs未更新は `[skip-docs]` 明示（バックエンド変更→フロント同期は本変更で対応するため docs更新は別途判断）
