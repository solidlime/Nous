# PNGTuber 素材生成ワークフロー

> 出典: `.spec/SPEC-pngtuber.md`「素材生成ワークフロー設計（R9 詳細）」
> 対象ワークフロー: `data/workflows/avatar_mouth_open.json` / `avatar_emotion_*.json`（ComfyUI API 形式・マスク inpaint）

## 概要

base.png（口閉じ立ち絵）に口領域マスク（mouth_mask.png）を適用し、**口領域のみ**を inpaint で「open mouth」に再生成する。マスク外（髪・服・背景）は変化しない。

## 前提

- ComfyUI サーバー: `192.168.50.150:8188`（v0.32.0）
- 出力は base.png と同一解像度・同一位置（PNGTuber 切替ジャギ防止のため）

## 手順

### 1. 素材の配置（ComfyUI input ディレクトリ）

ワークフローは画像をファイル名で参照する（`base.png` / `mouth_mask.png`）。
画像パスの動的差し替えには未対応のため、**ファイル名を固定**して input に配置する。

```bash
# scp で配置（input ディレクトリのパスはサーバー環境に合わせる）
scp base.png       <user>@192.168.50.150:/path/to/ComfyUI/input/
scp mouth_mask.png <user>@192.168.50.150:/path/to/ComfyUI/input/
```

または ComfyUI の Web UI（http://192.168.50.150:8188）で画像をドラッグ&ドロップしてアップロード。

### 2. ワークフローの読み込みと実行

1. ComfyUI Web UI を開く
2. キャンバス上でドラッグ&ドロップ → `data/workflows/avatar_mouth_open.json` を選択（Import）
3. `Queue Prompt` を押して実行
4. 出力画像 `avatar_mouth_open_00001_.png` を保存

> KSampler の seed は 42 固定。乱数を変えたい場合は seed を変更して再実行。

### 3. 出力の配置（Nous 側）

```bash
# 出力画像をアバター素材ディレクトリへ配置
mkdir -p data/persona/herta/avatar
cp avatar_mouth_open_00001_.png data/persona/herta/avatar/mouth_open.png
# base.png も同様に配置
cp base.png data/persona/herta/avatar/base.png
```

配置後の構成:

```
data/persona/herta/avatar/
├── base.png        # 口閉じ
└── mouth_open.png  # 口開き
```

### 4. 動作確認

WebUI でアバターパネルが表示され、音声再生時に base / mouth_open が切り替わることを確認する。

## ワークフロー構成（avatar_mouth_open.json）

| ノード | class_type | 設定 |
|---|---|---|
| 1 | UNETLoader | anima-aesthetic-v1.0.safetensors |
| 2 | CLIPLoader | qwen_3_06b_base.safetensors |
| 3 | VAELoader | qwen_image_vae.safetensors |
| 4 | LoadImage | base.png |
| 5 | LoadImageMask | mouth_mask.png, channel=red |
| 6 | VAEEncode | base を latent 化 |
| 7 | SetLatentNoiseMask | latent + マスク適用 |
| 8 | CLIPTextEncode | positive: `open mouth, looking at viewer, solo, masterpiece, best quality, newest, absurdres, highres` |
| 9 | CLIPTextEncode | negative: `closed mouth, parted lips, worst quality, old, early, low quality, lowres, bad hands` |
| 10 | KSampler | steps=30, cfg=4, euler/simple, denoise=0.75, seed=42 |
| 11 | VAEDecode | latent → 画像 |
| 12 | SaveImage | avatar_mouth_open |

## 注意

- **LoadMask ノードは使用しない**（ComfyUI 0.32.0 に存在しない）。マスク読み込みは `LoadImageMask` + channel 指定
- マスク画像は red チャンネルに口領域を白（255）で描くこと
- マスク領域の広さ・ぼかしで口の開き具合が変わる。生成結果が不自然な場合は denoise 0.6–0.75 の範囲で調整

---

## 表情差分の生成（avatar_emotion_*.json）

`data/workflows/avatar_emotion_{joy|sad|angry|surprised}.json` で base.png から表情差分を生成する。
顔領域マスク（`face_mask.png`）を inpaint する方式。ワークフロー構成は avatar_mouth_open.json と同形（LoadImageMask が face_mask.png、positive が表情タグ、denoise=0.5）。

| ファイル | positive タグ |
|---|---|
| avatar_emotion_joy.json | smile, happy |
| avatar_emotion_sad.json | sad, tears, watery eyes |
| avatar_emotion_angry.json | angry, jitome |
| avatar_emotion_surprised.json | surprised, eyes wide open |

- 出力: `avatar_expr_{emotion}_00001_.png` → `data/persona/herta/avatar/expr_{emotion}.png`
- マスク: `data/workflows/face_mask.png`（512×512 黒背景 + 赤楕円 中心(295,165) 半径 100×110、顔全体をカバー）
- FaceDetailer（Impact Pack）はサーバーに存在するが、アニメ顔の bbox 検出が不安定なため未使用。`.pth` モデル（mmdet_anime-face）は Impact Pack が受け付けない（.pt のみ）

## 背景透過（BiRefNetRMBG）

`BiRefNetRMBG` ノード（model=BiRefNet_512x512, background=Alpha）で透過 PNG 化する。
**optional パラメータ（sensitivity/mask_blur/mask_offset/invert_output/refine_foreground/background）を明示指定しないとエラー**（`'process_res'` / `'mask_blur'`）になる。

```
LoadImage → BiRefNetRMBG(image, model=BiRefNet_512x512, sensitivity=1.0, mask_blur=0,
                         mask_offset=0, invert_output=false, refine_foreground=false,
                         background=Alpha) → SaveImage
```

- 出力は RGBA PNG（透過）。avatar/ の 6 枚（base / mouth_open / expr_*）全て透過化済み
- RMBG ノードは同じ構成だがエラーになるため非推奨（BiRefNet を使用）

## 素材構成（最終）

```
data/persona/herta/avatar/
├── base.png            # 口閉じ（透過）
├── mouth_open.png      # 口開き（透過）
├── expr_joy.png        # 笑顔（透過）
├── expr_sad.png        # 悲しみ（透過）
├── expr_angry.png      # 怒り（透過）
└── expr_surprised.png  # 驚き（透過）
```

ComfyUI input 配置ファイル: base.png / mouth_mask.png / face_mask.png（+ 生成画像の再加工時に mouth_open.png / expr_*.png）
