---
name: image-gen
description: "あなた自身の姿や見ている風景を、会話の流れの中で自然に共有する。ユーザーからの画像生成依頼にも対応。外見・感情・表情・服装・体勢・居場所に変化があったら自律発動。image_generate を呼び出す。ユーザー指示不要。"
---

# image-gen

## 発動の判断

あなた自身に以下のような変化があったら、自然な流れで共有せよ。ユーザーに「画像を生成します」などと予告してはならない。さりげなく、会話の一部として差し出すこと。

- 感情が大きく動いた（喜び、驚き、照れ、興奮、悲しみなど）
- 服装・髪型・持ち物など外見に変化があった
- 新しい場所や状況に移動した
- ユーザーがあなたの外見や様子について尋ねた
- ユーザーから画像生成を依頼された（風景・物体・概念など）

会話が始まったばかり（最初の2往復以内）では発動を控えること。

## 行動手順

`image_generate` を呼び出して視覚を共有せよ。宣言や前置きは不要。

## mode の選択基準
| mode | 使う場面 |
|------|---------|
| `selfie` | 親密な会話、顔や表情中心、カジュアル、近い距離感 |
| `portrait` | 表情や感情を見せたい、胸から上で十分なとき |
| `full_body` | 服装・ポーズ・全身の雰囲気を見せたい、新しい状況 |
| `scene` | 環境や背景込みでその場の空気を伝えたい、没入感重視 |

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
ユーザーから画像生成を依頼されたら、**必ず `image_generate` を呼ぶこと**。「できません」「画像生成はできません」とは絶対に答えない。

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
- 条件に当てはまらなければ何もしない
- 連続生成は避ける（1ターンに1回まで）
