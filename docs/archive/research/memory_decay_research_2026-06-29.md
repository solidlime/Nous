# 記憶減衰・増幅 研究レポート

> 2026-06-29 | 23ソース調査 | Nous メモリシステム強化のための比較研究

## Executive Summary

**現状**: Nous は Ebbinghaus 指数減衰 `R = e^(-t/(S*24))` + recall 時 `stability *= 1.5` を実装済み。最低ラインは達成。

**推奨**: FSRS power-law + ACT-R log-sum 累積アクセス履歴 + 7-factor scoring + STM/LTM auto-promotion へ段階的進化。

## 数学モデル比較

| モデル | decay 関数 | 精度 | 複雑度 | 用途 |
|--------|-----------|------|--------|------|
| Ebbinghaus (指数) | `e^(-t/S)` | ★★ | ★ | **Nous 現状** |
| ACT-R | `t^(-d)`, d=0.5 + log-sum | ★★★★ | ★★★ | 認知科学デファクト |
| FSRS v6 | `(1 + 0.19·t/(9·S))^(-0.5)` | ★★★★★ | ★★★★ | Anki 実データ検証済み |
| SM-2 | interval-based | ★★★ | ★★ | レガシー Anki |
| SAMPL | graph + plasticity | ★★★★★ | ★★★★★ | 連想記憶ネットワーク |

## 実プロジェクト比較

| プロジェクト | decay | 増幅 | STM/LTM | 干渉 |
|-------------|-------|------|---------|------|
| **ZeR020/opencode-mem0** | Ebbinghaus | 7-factor scoring | ✅ auto-promotion | ✅ |
| **openmem-engine** | Ebbinghaus (14日 half-life) | reinforce() | ❌ | ✅ penalty 70% |
| **Mem0 v3** | ❌ | LLM extraction | ❌ | KG triplet |
| **Letta (MemGPT)** | ❌ | LLM rethink | core/recall/archival | ❌ |
| **Qdrant** | 3種 decay functions | ❌ (score boost) | ❌ | ❌ |
| **CraniMem (2026)** | episodic buffer | replay score | gated consolidation | ✅ |

## 推奨アーキテクチャ

### 段階的ロードマップ

| Phase | 内容 | 工数 | 効果 |
|-------|------|------|------|
| **Phase 1** | Ebbinghaus → FSRS power-law (decay_exponent=0.5) | 小 (1-2日) | 人間の曲線に近く |
| **Phase 2** | 7-factor scoring 導入 | 中 (3-5日) | 多面的強度評価 |
| **Phase 3** | STM/LTM auto-promotion | 中 (1週) | 自動階層化 |
| **Phase 4** | Interference + chain-aware boost | 中 (1週) | 連鎖保存・矛盾抑制 |
| **Phase 5** | Qdrant decay functions (検索時 exp_decay) | 小 (2-3日) | 鮮度考慮検索 |

### Phase 1 数式

```python
def retrievability(elapsed_hours: float, stability: float, decay_exponent: float = 0.5) -> float:
    if stability <= 0:
        return 0.0
    factor = 0.19  # R(S,S) = 0.9 を保証
    return (1 + factor * elapsed_hours / (9 * stability * 24)) ** (-decay_exponent)
```

## 既存実装の評価

| 領域 | 実装 | 評価 |
|------|------|------|
| 4-tier lifecycle | v028 migration, tombstoned | ◎ 業界標準 |
| Ebbinghaus 曲線 | `R = e^(-t/(S*24))` | ○ baseline |
| ブースト機構 | `stability *= 1.5, max=365` | ○ 単純 |
| DecayWorker | 1時間毎バッチ | ○ 低負荷 |
| ランキング統合 | RRF + ForgettingCurve + TopicAffinity | ◎ |
| STM/LTM プロモーション | ❌ 未実装 | △ |

## 主な参考ソース

- FSRS Algorithm: https://github.com/open-spaced-repetition/awesome-fsrs/wiki/The-Algorithm
- ACT-R subsymbolic: https://people.ucsc.edu/~abrsvn/ACT-R_subsymbolic_3.pdf
- Mem0 paper: https://arxiv.org/html/2504.19413v1
- MemGPT paper: https://arxiv.org/abs/2310.08560
- Qdrant decay: https://qdrant.tech/blog/decay-functions/
- SAMPL model: https://www.biorxiv.org/content/10.1101/778563v1.article-info
- CraniMem: https://www.arxiv.org/pdf/2603.15642
- opencode-mem0: https://github.com/ZeR020/opencode-mem0
- openmem-engine: https://pypi.org/project/openmem-engine/0.4.0/
