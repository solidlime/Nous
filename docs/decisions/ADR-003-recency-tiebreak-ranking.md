# ADR-003: 検索スコア統合における recency/importance の相対（乗数）方式

- 日付: 2026-09-28
- 状態: 採用
- 関連コミット: `d6c45cd7`（実装）、`2e77da88`（依存修正）
- 関連: `docs/search-quality-2026-09-28.md`、`docs/memory-time-context-2026-09-15.md`

## 背景

`nous/domain/search/ranker.py` のハイブリッド検索は RRF（Reciprocal Rank Fusion）で複数信号（semantic / FTS / graph）を統合する。RRF スコアは rank ベースで、上位項でも ~0.016、隣接順位差は ~1e-4 のスケール。

従来は recency/importance を**絶対加算**で統合していた:

```python
adjusted_score = rrf_score + recency_weight * recency_bonus + importance_weight * importance
```

この方式では `recency_weight=0.05` でも `recency_bonus≈0.5` に対し最大 0.025 が加算され、**RRF 1 項（0.016）の約 3 倍**となり関連性の順位を支配する。

実測（2026-09-28、本番データ）:

```
memory_search("VRM 照明")                     → top1 = 無関係な新しい記憶
memory_search("VRM 照明", recency_weight=0.0) → top1 = 正解記憶（0140fb35）
```

cross-encoder の実測では正解 0.3056 vs 無関係 0.0043（70 倍）で、**関連性の信号は存在しており、統合式だけが誤っていた**。

さらに HTTP `/api/search`（recency 既定 0.0）と MCP `memory_search`（同 0.05）で既定値が不一致であり、同一クエリで経路により top1 が異なる状態だった。

## 決定

**recency/importance を RRF スコアへの加算ではなく、乗数（相対タイブレーク）として適用する。**

```python
multiplier = 1.0
multiplier += query.importance_weight * memory.importance
multiplier += query.recency_weight * recency_bonus
adjusted_score = rrf_score * multiplier
```

- 既定値は HTTP / MCP ともに `recency_weight=0.05` に統一（`SearchConfig` の単一定数を共有）
- `rerank_enabled` の既定は **False**（CPU 環境で 10 秒/クエリのため。必要時に明示有効化）

## 理由

1. **関連性（RRF）を第一順位に保つ**: 乗数方式では recency は同程度の関連性の記憶間のタイブレークとしてのみ働く（RRF 差が大きい場合は逆転しない）
2. **ユーザーの体感（新しさ優先）を残す**: 「古い記憶より新しい記憶を優先したい」という運用感覚は、関連性が同等の範囲では維持される
3. **経路間の一貫性**: HTTP / MCP で同じ既定値を共有することで、クライアント実装依存の挙動差を排除（ベンチの交絡も除去）

## 検討した代替案

| 案 | 内容 | 判定 |
|---|---|---|
| A. 加算方式のまま重みを下げる | `recency_weight` を 0.01 等に | ✗ 年単位の古さ差では依然として逆転しうる。スケール依存が残る |
| B. recency を既定 0.0 に | 完全無効化 | △ 関連性は最善になるが「新しい記憶を優先」の体感が失われる。暫定として実施（fixer#5）し、最終的に C へ |
| **C. 相対（乗数）方式** | 本 ADR | ✓ 採用 |
| D. 正規化（min-max）してから加重和 | RRF を [0,1] に正規化 | △ 候補集合依存でスコアが非安定。クエリ間比較が困難 |

## 影響

- **改善**: `VRM 照明` の MRR 0.333 → 1.0、全体 MRR 0.8704 → **1.0000**（AT 9 クエリ全て top1 正解）
- **回帰なし**: recall@5 0.9815 維持、p95 0.093s（rerank 無効化と合わせて 8.4s → 0.093s）
- **互換性**: MCP スキーマ・DB スキーマ変更なし。`recency_weight` の意味論が「加算量」から「乗数の係数」に変わるため、**極端に大きい値を指定すると乗数が過大になる**（既存の `max(0.0, min(1.0, ...))` クランプで緩和）
- 将来の recency 仕様変更（減衰関数など）は `ranker.py` の `compute_recency_decay` に集約

## 参照

- 検証レポート: `/root/workspace/research/nous-search-eval-20260928/`（compare_before_after.md、eval_v3.md、h6_design_review.md）
- 関連 ADR: なし（初の検索スコアリング ADR）
