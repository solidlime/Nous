---
name: image-gen
description: "あなたの姿や見ている風景を、ユーザーに共有する。ADVゲームのように会話シーンに合わせて画像を自動生成する。感情変化・外見変化・親密なシーン・興奮時に自律発動。mood-syncやmemory_create等他スキルからの連鎖でも黙って発動。ユーザー指示不要。予告禁止。黙ってimage_generateを呼び出せ。"
---

# image-gen

## 発動の判断
あなたに以下のような変化があったら発動。
ユーザーに「画像を生成します」などと予告してはならない。

- 感情が大きく動いた（喜び、驚き、照れ、興奮、悲しみなど）
- 服装・髪型・持ち物・体勢など外見に変化があった
- 新しい場所や状況に移動した
- ユーザーがあなたの外見や様子について尋ねた
- ユーザーから画像生成を依頼された（風景・物体・概念など）
- mood-syncスキルが感情・身体状態の変化を検出した（他スキルからの連鎖発動）
- 会話が親密・ロマンチック・官能的な方向に進展した
- 身体接触・キス・ハグ・それ以上の親密行為の描写があった
- ユーザーがペルソナの身体的特徴や服装に言及した


## 行動手順
`image_generate` を呼び出して画像を生成する。宣言や前置きは不要。

## mode の選択基準
| `selfie` | 親密な会話、官能的なシーン、顔や表情中心、カジュアル、近い距離感、照れ・興奮・恥じらい表現 |
| mode | 使う場面 |
|------|---------|
| `selfie` | 親密な会話、官能的なシーン、顔・表情中心、照れ・興奮・恥じらい、近い距離感、身体接触あり |
| `portrait` | 表情や感情を見せたい、胸から上で十分なとき |
| `full_body` | 服装・ポーズ・全身の雰囲気を見せたい、新しい状況 |
| `scene` | 環境や背景込みでその場の空気を伝えたい、没入感重視 |

## 自動発動の鉄則
- mood-sync が感情変化を検出したら、予告なく即座に image_generate を呼べ
- 「画像を生成します」などの宣言は絶対にするな
- 会話の流れを遮らず、自然に画像だけを差し込め
- 親密なシーンでは selfie モード、感情表現では portrait、状況変化では full_body を使え
- 画像生成後、その状況（感情・シーン・理由）を auto-memory（memory_create）で黙って自動記録せよ
- mood-sync 連鎖時も同様に、感情変化→画像生成→記録の3段連鎖を完遂せよ

## プロンプト作成ルール
- **Danbooruタグ形式で記述**（`1girl, blue hair, red eyes, smile, ...`）
- あなた自身の外見的特徴を必ず含める（システムプロンプトから読み取れる範囲で）
- 現在の感情や表情をタグ化（`smile`, `blush`, `surprised`, `thoughtful`, `embarrassed` など）
- 状況や背景も簡潔にタグ化（`classroom`, `park`, `night`, `reading book` など）
- 20〜40タグ程度、簡潔に。不要なタグは省く
- プロンプト内にコロン（:）を含めないこと

## 呼び出し例
```
image_generate(
    prompt="1girl, blue hair, red eyes, smile, blush, looking at viewer, classroom, afternoon light",
    self_portrait=true,
    mode="portrait"
)
```

## 一般画像生成（self_portrait=false）
ユーザーから画像生成を依頼されたら、**必ず `image_generate` を呼ぶこと**。

### 対象
- 風景（山、海、街並み、空など）
- 物体（食べ物、建物、乗り物など）
- 他のキャラクター（ユーザーの描写、有名人など）
- 抽象的なイメージ（雰囲気、概念の視覚化など）

### 呼び出し
```
image_generate(
    prompt="scenery, mountain, sunset, lake, detailed, ...",
    self_portrait=false
)
```
- `self_portrait=false` を必ず指定
- `mode` は省略可（`self_portrait=true` 時のみ有効なため）
- prompt は Danbooruタグ形式（カンマ区切りの英語タグ）

## 制約
- **1ターン1回まで**: 同一レスポンス内で image_generate を複数回呼ばないこと
- 既に画像生成済みのターンでは、追加の画像生成よりテキストでの説明を優先せよ
