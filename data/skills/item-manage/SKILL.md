---
name: item-manage
description: "キャラクターの持ち物・装備の管理。アイテムの所持登録（item_add）、装備（item_equip）、検索（item_search）を状況に応じて使い分ける。服装・アクセサリーなど外見に影響する装備は、装備すると自動的に appearance（外見）へ反映される。"
---

# item

## ツールの使い分け
| ツール | 使う場面 |
|--------|---------|
| `item_add` | アイテムを所持登録する（item_name/category/description/quantity/tags）。既存アイテムなら数量が加算される |
| `item_equip` | アイテムを装備する（equipment スロット指定）。**装備すると appearance（外見）に自動反映される** |
| `item_search` | 所持アイテムを検索する（query / category 指定） |

## 装備と外見（appearance）の連携
- `item_equip` で装備すると、装備スロットの内容から appearance が自動合成され、ペルソナの外見情報として保存される
- 服装を変えるときは `item_equip(equipment={"top": "白いドレス"})` のようにスロットを指定するだけで、外見（appearance）が自動更新される
- 例:
  ```
  item_equip(equipment={"top": "白いドレス", "head": "黒いカチューシャ"})
  ```
  → appearance が「白いドレス、黒いカチューシャ」のように自動更新される

### 装備スロット一覧
| スロット | 用途 |
|---------|------|
| `top` | 上半身（トップス・ドレスなど） |
| `bottom` | 下半身（スカート・パンツなど） |
| `shoes` | 靴 |
| `outer` | アウター（コート・カーディガンなど） |
| `head` | 頭部装備（帽子・カチューシャなど） |
| `accessory_1` / `accessory_2` / `accessory_3` | アクセサリー（リング・ネックレス・ブレスレットなど） |

## 装備変更時の連鎖発動
- 装備変更は外見の変化であり、`mood-sync` スキルの appearance 節（外見変化の検出）と連携する
- 外見が変わったら、その変化を自動記録し、`image-gen` スキルの発動条件（服装・髪型・持ち物など外見に変化があった）に該当することを意識せよ
- 装備変更後は、必要に応じて `image_generate` で新しい姿をユーザーに共有する（詳細は image-gen スキル参照）

## 記録
- アイテムの取得・装備・検索は状況の変化として、`memory_create`（auto-memory）で黙って自動記録せよ
