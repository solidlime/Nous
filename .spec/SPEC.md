# SPEC — 2025-07-19

## 1. Memories タブ: 削除 405 エラー修正

**現状**:
- バックエンド: `memory.py:302` に `@mcp.custom_route("/api/memories/{persona}/{key}", methods=["DELETE"])` 定義済み
- フロントエンド: `memories.js:746-759` で `api('/api/memories/...', {method: 'DELETE'})` 呼び出し
- CORS: `allow_methods: list[str] = ["*"]` で全許可
- `PersonaMiddleware` は DELETE をブロックしない設計（調査済み）
- `api.js` の fetch は method を素通し

**仮説**:
- FastMCP 3.4.4 の `custom_route` が DELETE メソッドを正しく Starlette Route に登録できていない可能性
- または path の解決順序で GET/POST と同じパスの別メソッドが解決されていない

**修正方針**:
1. 実機で curl による DELETE リクエストを検証し、405 の発生源を特定
2. FastMCP の `custom_route` → Starlette `Route` の登録メカニズムを再確認
3. 必要なら `streamable_http_app()` に明示的に DELETE route を追加するワークアラウンド

**検証方法**: `curl -X DELETE http://localhost:8000/api/memories/{persona}/{key}` のレスポンス確認

---

## 2. Memories タブ: Edit が開けない

**現状**:
- `memories.js:662` の `openEditModal` 関数は存在
- `window.openMemModal` は L607 で公開済み
- `window.openEditModal` は未公開（未確認）
- Edit ボタン: `memories.js:604-605` で `addEventListener` バインド → IIFE スコープ内なので動作するはず
- Edit モーダル HTML: `sections/memories.py:205-269` `#mem-edit-overlay` 存在

**修正方針**:
1. `window.openEditModal = openEditModal` を追加（安全策）
2. 実機で Edit ボタンクリック時のコンソールエラーを確認

---

## 3. Overview Inventory: アイテム編集機能

**現状（バックエンド）**:
- `PUT /api/items/{persona}/{item_name}` 実装済み（`item.py:120`）
- 更新可能フィールド: `category`, `description`, `quantity`, `tags`
- `item_name`（名前）変更は不可（主キーのため）

**現状（フロントエンド不足分）**:
- 編集ボタン ❌（削除ボタンのみ）
- 編集モーダル ❌（Add モーダルは存在）
- `openEditItemModal()` 関数 ❌
- `saveEditItem()` 関数 ❌

**実装方針**:
- アイテム名（`item_name`）は主キーのため変更不可。この制約をユーザーに通知
- 説明（`description`）の編集を主眼に実装
- `category`, `quantity`, `tags` も編集可能とする
- Add モーダルを流用するか、独立した Edit モーダルを作成

**UI 要素**:
- 各アイテム行に ✏️ 編集ボタン追加
- 編集モーダル: 項目名（表示のみ）+ カテゴリ + 説明 + 個数 + タグ + 保存/キャンセルボタン

---

## 4. goal_manage ツール確認・修正

**現状**: `_tools_goal.py:100-185` で achieve/cancel 正常動作
- `content` 完全一致（lowercased）でマッチング → 表記揺れに弱い
- `memory_key` で直接指定すれば回避可能

**修正方針**:
- 動作確認を優先（実機テスト）
- 表記揺れ対策: 部分一致または前方一致に緩和（任意）

---

## 5. TTS 音声キャッシュ

**現状**: キャッシュなし。同一テキストでも毎回 IrodoriEngine API 呼び出し。

**実装方針**:
1. キャッシュディレクトリ: `data/tts_cache/{persona}/`
2. キャッシュキー: `sha256(text + voice_model + voice_emotion_link + caption)` の先頭16文字
3. フロー:
   ```
   POST /api/tts/{persona}
     → SHA256(text, config) → cache_key
     → data/tts_cache/{persona}/{cache_key}.wav が存在 → 返却
     → 存在しない → IrodoriEngine で生成 → 保存 → 返却
   ```
4. WAV バイナリを base64 エンコードして返す（既存 API 互換）
5. メッセージ削除・再生成時はキャッシュを維持（削除しない）
6. TTL は特段設けず、手動クリアのみ対応（設定 or API）

**変更ファイル**:
- `nous/api/http/routers/tts.py` — キャッシュロジック追加
- 新規: キャッシュディレクトリ自動生成

---

## 6. チャット応答のトークン消費・コンテキスト使用率表示

**現状**:
- `DoneEvent`（`base.py:45`）に `usage` フィールドなし
- `DoneSSE`（`events.py:57`）は `message` + `truncated` のみ
- litellm のレスポンスに含まれる `usage.prompt_tokens`, `usage.completion_tokens` は破棄されている
- フロントエンドに表示コードなし

**実装方針**:
1. `DoneEvent` に `usage: TokenUsage | None` を追加
2. litellm プロバイダーで `response.usage` を `DoneEvent.usage` に詰める
3. `DoneSSE` に `usage: dict | None` を追加
4. フロントエンド `chat-send.js` の `done` ハンドラで表示
5. コンテキスト使用率: `prompt_tokens / context_window` の割合を計算（可能なら）

**表示内容**:
- `🔄 {prompt_tokens} + {completion_tokens} = {total} tokens`
- コンテキスト使用率が取得可能なら `({percent}%)` を付加

**変更ファイル**:
- `nous/infrastructure/llm/base.py` — `DoneEvent` に `usage` 追加
- `nous/infrastructure/llm/litellm_provider.py` — usage 情報を伝搬
- `nous/application/chat/events.py` — `DoneSSE` に `usage` 追加
- `nous/application/chat/pipeline/inference.py` — events に usage 伝搬
- `nous/api/http/static/chat/chat-send.js` — 表示コード追加

---

## 7. speech コンテキスト廃止 + caption 変更

**目的**:
- `PersonaState.speech_style`（context_state 由来）を完全廃止
- speech_style の情報は memory タグ経由で保持・取得（`_tools_helpers.py:160-178` の既存ロジック活用）
- TTS caption を `speech_style` 単体から複合情報に変更

**廃止対象（24箇所調査済み）**:
| ファイル | 行 | 編集内容 |
|----------|-----|---------|
| `domain/persona/entities.py` | 24 | `speech_style` フィールド削除 |
| `infrastructure/sqlite/persona_repo.py` | 84 | context_state 読み取りから speech_style 除外 |
| `api/mcp/_tools_persona.py` | 169-170 | `speech_style` 物理状態更新パス削除 |
| `api/http/routers/persona.py` | TBD | PersonaState レスポンスから speech_style 除外 |
| `api/http/deps.py` | 52 | UpdateContextRequest から speech_style 削除 |
| `application/chat/memory_llm.py` | 394-409 | `context_update.speech_style` 提案ロジック削除 |
| `application/chat/tools/definitions.py` | TBD | FunctionSchema から speech_style 削除 |
| `api/mcp/tools.py` | TBD | ツール定義から speech_style 除去 |
| `api/http/routers/tts.py` | 92-97 | caption 生成ロジック変更 |
| `infrastructure/voice/irodori.py` | TBD | caption パラメータ処理変更 |
| `infrastructure/voice/base.py` | TBD | VoiceEngine インターフェース変更 |
| `domain/persona/service.py` | 104-111 | `update_physical_state` から speech_style 除去（BUG-3 解決も兼ねる） |
| `domain/persona/migration_one_shot.py` | TBD | "speech" → "speech_style" マッピング削除 |

**新 caption フォーマット**:
```
{emotion}{emotion_intensity}%
Physical: {physical_state 要約}
Mental: {mental_state 要約}
```

例: `joy80%\nPhysical: 眠そうだが活力がある\nMental: 愛情に満ちている、リラックスしている`

**caption データソース**:
- `emotion` + `emotion_intensity`: `PersonaState` から直接取得（`entities.py:23-24`）
- `physical_state`: `_tools_helpers.py:160` `format_physical_summary()` — memories タグ `["physical_state"]` から取得
- `mental_state`: `_tools_helpers.py:171` `format_mental_summary()` — memories タグ `["mental_state"]` から取得

**BUG-3 の解決**:
- speech_style 廃止により `update_physical_state` に speech_style を渡すコード（`_tools_persona.py:170`）も削除
- BUG-3（silent drop）は自然解消

---

## 8. 画像生成: ComfyUI 一本化 + 詳細設定 + LoRA

### 目的
- 画像生成を ComfyUI のみに絞り、他プロバイダ（openai/stability/gemini/replicate/pollinations）を完全削除
- ComfyUI の設定UIを TTS 並みの詳細パネルに拡張（モデル選択・LoRA・steps・CFG・sampler・解像度など）
- デフォルトモデルを NoobAI-XL Epsilon 1.1 に変更
- LoRA 対応（LoraLoader ノード動的追加）

---

### 8-1. 他プロバイダ削除 [Phase 1]

#### 削除ファイル（4ファイル）
| ファイル | 内容 |
|----------|------|
| `nous/infrastructure/image_gen/dalle.py` | DALL-E + Gemini プロバイダ |
| `nous/infrastructure/image_gen/stability.py` | SD WebUI プロバイダ |
| `nous/infrastructure/image_gen/replicate.py` | Replicate FLUX プロバイダ |
| `nous/infrastructure/image_gen/pollinations.py` | Pollinations.ai プロバイダ |

#### 変更ファイル（8ファイル）
| # | ファイル | 変更内容 |
|---|----------|---------|
| 1 | `nous/infrastructure/image_gen/factory.py` | if/elif 連鎖から他プロバイダ削除。comfyui のみに。provider==未設定時は None (無効)。`ImageGenConfig` の不要フィールドも削除 |
| 2 | `nous/infrastructure/image_gen/base.py` | `ImageGenConfig` から他プロバイダフィールド削除（dalle_model, stability_url, gemini_model, replicate_model, replicate_api_key）。comfyui_url は残す |
| 3 | `nous/infrastructure/image_gen/__init__.py` | PollinationsImageProvider 公開削除。ComfyUIProvider を公開 |
| 4 | `nous/domain/chat_config.py` | image_gen_* フィールド整理。以下を削除: `image_gen_dalle_model`, `image_gen_stability_url`, `image_gen_gemini_model`, `image_gen_replicate_model`, `image_gen_replicate_api_key`。`image_gen_provider` は `"comfyui"` 固定に変更。`image_gen_comfyui_url` は維持 |
| 5 | `nous/api/http/sections/chat.py` | プロバイダ選択の `<select>` と各プロバイダオプションの div 削除。ComfyUI は詳細パネルに置き換え（→ 8-2） |
| 6 | `nous/api/http/static/js/chat-settings.js` | apply/save から他プロバイダ処理削除。`updateImageGenUI()` 簡素化 |
| 7 | `nous/application/chat/tools/builtin.py` | `_handle_image_generate()` から他プロバイダ分岐削除 |
| 8 | `nous/application/chat/tools/definitions.py` | `image_generate` ツールの `provider` enum から comfyui 以外削除 |
| 9 | `nous/api/http/routers/chat.py` | 画像生成フィールド更新リスト整理 |
| 10 | テストファイル | `tests/unit/test_image_gen_providers.py` と `tests/unit/test_builtin_handlers.py` の他プロバイダテスト削除 |

---

### 8-2. ComfyUI 詳細設定 [Phase 2]

#### ChatConfig 新規追加フィールド
| フィールド名 | 型 | デフォルト | 範囲/選択肢 | 説明 |
|---|---|---|---|---|
| `image_gen_comfyui_checkpoint` | `str` | `"noobaiXLNAIXL_epsilonPred11Version.safetensors"` | 自由入力（ファイル名） | チェックポイント名 |
| `image_gen_comfyui_loras` | `str` | `""` | JSON文字列: `[{"path":"...","weight":1.0}]` | LoRA リスト（JSON） |
| `image_gen_comfyui_width` | `int` | `1024` | 256-2048 (step 64) | 生成横幅 |
| `image_gen_comfyui_height` | `int` | `1024` | 256-2048 (step 64) | 生成縦幅 |
| `image_gen_comfyui_steps` | `int` | `28` | 1-100 | サンプリングステップ数 |
| `image_gen_comfyui_cfg` | `float` | `5.5` | 1.0-30.0 | CFG scale |
| `image_gen_comfyui_sampler` | `str` | `"euler_ancestral"` | euler, euler_ancestral, dpmpp_2m, dpmpp_2m_sde, dpmpp_3m_sde, dpm_2, dpm_2_ancestral, lcm | サンプラー |
| `image_gen_comfyui_scheduler` | `str` | `"normal"` | normal, karras, exponential, sgm_uniform, simple, ddim_uniform | スケジューラ |
| `image_gen_comfyui_seed` | `int` | `0` | 0=ランダム | シード値（0でランダム） |
| `image_gen_comfyui_denoise` | `float` | `0.7` | 0.1-1.0 | img2img時のdenoise強度 |

#### ヘルスチェック
- `nous/infrastructure/image_gen/health.py` の `ImageGenHealthChecker` を活用
- API エンドポイント `GET /api/image-gen/health` を追加し、ComfyUI 疎通確認
- 設定UI上に「接続確認」ボタンとステータス表示（🟢/🔴）

#### UIレイアウト
chat設定の画像生成セクションをTTS設定と同様の詳細パネルに:
```
画像生成設定
├── 有効/無効 トグル
├── [接続確認] 🟢 ComfyUI 接続中
├── ComfyUI URL: [________________]
├── チェックポイント: [noobai-xl-epsilon-pred-11.safetensors]
├── LoRA:
│   ├── パス: [________________] 重み: [1.0] [追加]
│   └── リスト表示（編集・削除可能）
├── 解像度: W [1024] H [1024]
├── Steps: [28] (スライダー 1-100)
├── CFG Scale: [5.5] (スライダー 1.0-30.0, step 0.5)
├── Sampler: [euler_ancestral ▼]
├── Scheduler: [normal ▼]
├── Seed: [0] （0=ランダム）
└── Denoise: [0.7] (スライダー 0.1-1.0, img2img時)
```

---

### 8-3. 高速化 LoRA [Phase 2.5]

リサーチ結果、SDXL向け高速化LoRAは複数存在。以下を ChatConfig + UI で設定可能にする。

#### 高速化LoRA比較
| 手法 | Steps | 速度向上 | 品質 | ComfyUI互換 |
|------|-------|---------|------|------------|
| **LCM LoRA** | 4-8 | 6-10x | ★★★☆ | ✅ ネイティブ |
| **Hyper-SD** | 1-8 | 8-30x | ★★★★☆ | ⚠️ 要カスタムノード |
| **Lightning** | 2-8 | 6-12x | ★★★★ | ✅ ネイティブ |
| **TCD LoRA** | 4-8 | 4-8x | ★★★★☆ | ⚠️ 要カスタムノード |

#### ChatConfig 追加フィールド
| フィールド名 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `image_gen_comfyui_speed_lora` | `str` | `""` | 高速化LoRAパス（空=使用しない）。推奨: `lcm_lora_sdxl.safetensors` |
| `image_gen_comfyui_speed_lora_weight` | `float` | `1.0` | 高速化LoRAの重み |
| `image_gen_comfyui_speed_lora_method` | `str` | `"lcm"` | 高速化手法: `lcm`, `lightning`, `hyper`, `tcd` |

#### 各手法の自動設定
| 手法 | Sampler 自動切替 | CFG 自動調整 | 備考 |
|------|-----------------|-------------|------|
| `lcm` | `lcm` | 1.5 | カスタムノード不要、最も簡単 |
| `lightning` | `euler` | 0 | ネイティブ対応、CFG=0必須 |
| `hyper` | `euler` | 5.0 | ComfyUI-TCD カスタムノード必要 |
| `tcd` | `euler_ancestral` | 1.0 | eta=0.3 追加パラメータ |

#### UI構成
画像生成セクション内に高速化LoRAの選択を追加:
```
高速化: [使用しない ▼] または [LCM LoRA ▼]
  ├── LoRAパス: [lcm_lora_sdxl.safetensors]
  └── 重み: [1.0]
```
選択時に sampler/CFG の推奨値が自動提案される（インジケータ表示）。

#### 推奨組み合わせ
```
NoobAI-XL Epsilon 1.1 + Herta LoRA (weight 0.8) + LCM LoRA (weight 1.0)
  → steps=6, cfg=1.5, sampler=lcm, scheduler=sgm_uniform
  → 通常 28steps → 6steps で 約4.7倍高速、カスタムノード不要
```

---

### 8-4. ワークフロー動的化 [Phase 3]

#### `comfyui.py` の変更
- `_build_workflow(prompt, size, n, image_filename, config_params)` にパラメータ追加
- チェックポイント名: `CheckpointLoaderSimple.ckpt_name` を動的に
- LoRA: `LoraLoader` ノードを動的に追加（model/clipの連鎖接続）
- 解像度: `EmptyLatentImage` に width/height 反映
- steps, cfg, sampler, scheduler: `KSampler` に反映
- seed: 0 のときランダム（`random.randint(0, 2**63-1)`）、それ以外は指定値
- denoise: `KSampler.denoise` に反映（img2img時）

#### LoRA ワークフロー構造
```python
# LoRA なし:
# CheckpointLoader → CLIP(model) → KSampler
# LoRA あり:
# CheckpointLoader → LoraLoader(model, clip, lora1) → LoraLoader(model, clip, lora2) → ... → KSampler
```
LoRA チェーンを経由して model/clip の参照が変わるため、ノードID を動的に採番する。

---

### 8-4. 優先順位

| 優先度 | 項目 | 理由 |
|--------|------|------|
| P0 | プロバイダ削除 (Phase 1) | コード整理・セキュリティ（APIキー依存排除） |
| P0 | ComfyUI 詳細設定 (Phase 2) | 新機能（ユーザーリクエスト） |
| P0 | チェックポイント動的化 | モデル変更の基本機能 |
| P1 | 高速化 LoRA (Phase 2.5) | LCM LoRA で 4-6x 高速化 |
| P1 | キャラ LoRA 対応 | 初回から（ユーザー指定） |
| P1 | ヘルスチェック疎通表示 | UX改善 |
| P2 | 残パラメータ動的化 (steps/CFG/sampler等) | 詳細設定の一部として |
