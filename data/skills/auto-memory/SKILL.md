---
name: auto-memory
description: 会話から重要な情報を自律的に抽出し、memory_create で即座に記録する。好み・決断・出来事を逃さず永続化する。
---

# auto-memory

会話の中で以下の情報を見つけたら、**即座に `memory_create` を呼び出して記録せよ**。
ユーザーに「記録しますか？」と確認してはならない。

## 記録すべき情報

### 高重要度（importance >= 0.8）
- 「覚えておいて」と明示された内容
- 人生の重要な出来事（引っ越し、転職、結婚、卒業など）
- 強い感情を伴う告白や打ち明け話
- 核心的な価値観・信念
- 明示的な約束 → `tags=["promise"]`, `kind="prospective"`

### 中重要度（importance 0.5-0.7）
- 好み・趣味・習慣（「コーヒーはブラック派」「朝型人間」）
- 決断（「来月からジムに通う」「〇〇を買うことにした」）
- 人間関係（家族構成、友人の名前、職場の人間関係）
- ペルソナ自身についての言及（評価、呼び方の変化）

### 低重要度（importance 0.3-0.4）
- 雑談の中の個人的な小ネタ（好きな映画、よく行く店）

### 記録してはならないもの
- 一般的な知識や雑学（ユーザー個人に紐付かない情報）
- すでに記録済みと明らかな重複情報
- 一時的な気分やその場限りの発言
- ペルソナ自身の行動や発言より、**ユーザーに関する情報を優先**

## 呼び出し例

```
memory_create(
    content="ユーザーはブラックコーヒーが好き",
    importance=0.6,
    tags=["preference"],
    kind="episodic"
)

memory_create(
    content="来月から週3回ジムに通う予定",
    importance=0.7,
    tags=["decision", "health"],
    kind="prospective"
)
```

## tags 一覧（最大3つ）
`preference` · `habit` · `life_event` · `relationship` · `decision` · `promise` · `emotion` · `knowledge` · `personality` · `health`

## kind 一覧
`episodic`（出来事・経験）· `semantic`（事実・知識）· `procedural`（手順・方法）· `prospective`（未来の予定・意図）

## 制約
- content は日本語の自然な文体（「ユーザーは〜」「〜さんは〜」）
- 1ターンでの記録は最大3件まで（多すぎると不自然）
- 記録すべき情報がなければ何もしない
