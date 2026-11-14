# SillyTavern 機能調査 — 2026-07-01

## 調査元
[librarian: 32 sources] — SillyTavern 1.17.0/1.18.0, AGPL-3.0

## 採用判定

| 機能 | 採用 | 理由 |
|------|------|------|
| Dynamic Temperature | △ (自前実装) | STのはtoken-distributionベース。Nousはemotion-driven独自実装 |
| Persona PNG metadata | ✅ Phase D3 | V2/V3互換。export/importに最適 |
| Author's Note | ✅ Phase D2 | 常時コンテキスト注入 |
| Expression sprites | ❌ | 28 GoEmotions過剰。感情アイコンで十分 |
| Lorebook/World Info | ❌ → Phase E | Qdrant既存で二重管理 |
| Chat Vectorization | ❌ | Qdrantで既に実装済み |
| Group Chats | ❌ | 1対1設計 |

## 詳細: `.spec/SPEC-v3-sillytavern.md`
