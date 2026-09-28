# 記録: 記憶検索精度の改善（日本語 OR 検索・semantic 死亡・recency 逆転の修正）

- 日付: 2026-09-28
- コミット: `d6c45cd7` fix(search): semantic 復活・rerank 範囲制限・recency タイブレークで検索精度を改善 / `02a691af` test(bench): 検索品質の評価ハーネスと検証用 Dockerfile / `c4dc534d` fix(ci): CI 赤の4原因を修正 / `2e77da88` fix(deps): sudachipy を <0.7.0 に固定
- 検証: nous-verify2（検証コンテナ）→ 本番 nous へデプロイ（2026-09-28 13:14 JST、コンテナ `45f6480e5ffe`）

## 症状（ユーザー報告）

「検索精度が悪い。特に日本語クエリ込みの OR 検索」。実例: `VRM 照明` で正解記憶（`memory_20260915014126_...0140fb35`）が top1 に来ない。

## 調査で確定した原因（6件）

1. **semantic（ベクトル）検索が本番で死亡していた**（最重要）
   - `nous/application/context/vector_stack.py` の `search_engine` プロパティが二重定義され、後勝ちの実装が `vector_store` の初期化を待たずに `None` を返す（`is_loaded` ガードで semantic 枝が丸ごとスキップされていた）
   - 実機ログに embedding モデルのロード形跡ゼロ、httpx のリクエストは Qdrant の health のみ → **FTS（キーワード）だけが動いていた**
   - 日本語一般語は FTS のトークナイズで候補プールが痩せ、OR 検索が成立しない

2. **rerank が本番経路で実質無効 + 適用範囲の実装ミス**
   - `SearchConfig.rerank_enabled` の既定が有効なのに、モデル未ロード時に警告なくスキップされる経路があった
   - 後から入れた「上位 20 件のみ rerank」制限（`fixer#1`）が、gold を圏外へ押し出す回帰を生んだ（後に recency が真因と判明、本制限自体は不要と判断）

3. **recency ブーストの絶対加算が順位を支配**（`nous/domain/search/ranker.py`）
   - `adjusted = rrf_score + recency_weight * recency_bonus` の加算方式。RRF スコアは ~0.016 スケール、recency 項は最大 0.025（約 3 倍）で、関連性を無視して新しい記憶が top1 に来ていた
   - oracle の反証実験（決定的）: `memory_search("VRM 照明")` → top1=無関係 / `recency_weight=0.0` → top1=gold
   - cross-encoder 実測では gold 0.3056 vs 無関係 0.0043（70 倍）で、**正解の信号は存在し、統合式だけが誤っていた**

4. **HTTP `/api/search` と MCP `memory_search` の recency 既定値が不一致**（0.0 vs 0.05）
   - 同一クエリで経路により top1 が異なる（ベンチの交絡にもなっていた）

5. **H6（グラフ信号）が本番経路で short-circuit により捨てられていた**
   - ハイブリッド検索の候補プール生成後、graph expansion が `use_graph` 未指定時に常に無効化されていた（追加計算ほぼゼロで再有効化可能）

6. **rerank の 10 秒レイテンシ**（CPU: Celeron J4125）
   - cross-encoder を 20 件に適用すると 10 秒/クエリ。合格ライン（p95 ≤ 1.5s）に不適合

## 実装（修正1〜6）

| # | 内容 | 主なファイル |
|---|---|---|
| 修正1 | semantic 復活（`search_engine` の二重定義解消・`is_loaded` ガード修正） | `nous/application/context/vector_stack.py` |
| 修正2 | H6: グラフ信号の本番経路有効化 + 候補の再 encode 排除 | `nous/domain/search/engine.py`, `policy.py`, `vector_stack.py` |
| 修正3 | `SearchConfig.rerank_enabled=False`（既定無効化）+ `keyword_weight` 0.5→1.0 | `settings.py`, `engine.py`, `ranker.py` |
| 修正4 | MCP/chat の `keyword_weight` 既定を 1.0 に統一 | `mcp/tools.py`, `_tools_memory.py`, `definitions.py`, `ranker.py` |
| 修正5 | recency 既定値の統一（暫定 0.0） | 同上 |
| 修正6 | **recency を相対（乗数）方式のタイブレークに変更**。`adjusted = rrf_score * multiplier`（`multiplier` は 1.0 起点で importance/recency をスケール）。既定 0.05 を HTTP/MCP で統一 | `ranker.py`, `settings.py`, `engine.py` |

全て追加的・後方互換（DB スキーマ無変更、MCP スキーマ互換）。

## ベンチ結果（before/after）

評価ハーネス: `tests/benchmark/` + `scripts/eval_search_quality.py`（12 クエリ、gold は all-term 定義、計測可能 9 件）

| 実行 | 状態 | zero-result | recall@5 | MRR | p95 latency |
|---|---|---|---|---|---|
| baseline_v1 | 本番（semantic 死） | 1 | 0.5556 | 0.7284 | — |
| verify_v1 | 修正1 | 0 | 0.9259 | 0.8704 | 8.4s（rerank） |
| verify_v2 | 修正1+2 | 0 | 0.9259 | 0.8704 | 8.4s（rerank） |
| eval_v3_warm | 修正1〜4 | 0 | **0.9815** | 0.8704 | **0.097s** |
| **最終（fixer#6）** | **修正1〜6** | **0** | **0.9815** | **1.0000** | **0.093s** |

- **recall@5: 0.5556 → 0.9815**（+77%）
- **MRR: 0.7284 → 1.0000**（AT 9 クエリ全て top1 正解）
- **p95: 8.4s → 0.093s**（rerank 既定無効化）
- 合格ライン（案C）: zero-result 0 / recall@5 ≥ 0.75 / MRR ≥ 0.80 / p95 ≤ 1.5s → **全達成**

## デプロイ手順（再現用）

1. **CI 緑 + Docker Build & Push 成功を確認**（`ghcr.io/solidlime/nous:latest` が更新される）
2. **バックアップ**: Qdrant の全コレクションをスナップショット（本番データは触らない）
3. **デプロイ（watchtower 経由、`sh` 不要）**:
   ```bash
   # mcp-hub コンテナ（docker.sock をマウント済み）から Docker API で watchtower を exec
   # /tmp/wt2.py 相当: POST /containers/watchtower/exec {"Cmd":["/watchtower","--run-once","nous"]}
   #                   → POST /exec/{id}/start {"Detach":true}（レスポンスは読まずに切断）
   ```
   - watchtower コンテナは distroless で `sh` が無いため、Portainer の exec（`sh -c` 経由）は使えない。**Docker API を直接叩く**
   - watchtower の定期ポーリング（毎日 13:46 JST 頃）と競合しないよう、実行前に `date` で時刻確認
4. **確認**:
   - `curl http://nas:26262/health` → `{"status":"ok","version":"4.0.1","qdrant":"connected"}`
   - 新コンテナ ID を `/proc/1/cgroup` で確認（旧 ID と変わる）
   - コード検証: `grep -n 'recency_weight' /app/nous/domain/search/engine.py`（既定 0.05）、`ranker.py` の `multiplier`
   - 実検索: `curl 'http://nas:26262/api/search/herta?q=VRM%20照明&limit=5'` → gold が top1

## 評価ハーネスの使い方（再現）

```bash
cd /root/workspace/research/nous-search-eval-20260928
# 検証環境（MCP 経由）
python3 run_eval.py --base-url http://nas:26264 --transport mcp \
  --host-header localhost:26264 --persona herta \
  --corpus ./herta_corpus.json --queries ./queries_v1.json --out verify_vX
# 本番（読み取りのみ）
python3 run_eval.py --base-url http://nas:26262 --persona herta \
  --corpus ./herta_corpus.json --queries ./queries_v1.json --out baseline_vX
```

- gold コーパス: `herta_corpus.json`（1026 件、`payload.content` に本文）
- クエリセット: `queries_v1.json`（ja_or 6 / ja_single 1 / proper 2 / en 2 / generic_np 1）
- リポジトリ内の pytest 版: `tests/benchmark/`（`uv run pytest tests/benchmark -m benchmark`）

## 教訓

- **「精度が悪い」の一次切り分けは semantic の生存確認から**。FTS だけが動いていても検索は「動く」ので、症状が精度劣化として現れる。ログ（embedding ロード形跡）と返却件数の痩せで判別できる
- **スコア統合式のスケール差に注意**: RRF（rank ベース、隣接差 ~1e-4）に絶対値の重み項を足すと、重みが小さくても順位を支配しうる。相対（乗数）方式が安全
- **経路ごとの既定値不一致はベンチの交絡になる**。HTTP/MCP で同じ既定値を共有すること
- **rerank は CPU 環境で 10 秒/クエリ**。既定無効化が正解（必要時に明示有効化）
- **Portainer 経由の exec は `sh -c` 固定**。distroless コンテナ（watchtower）には Docker API 直叩きが必要
- **sudachipy 0.7.x は V0 形式辞書を読めない**（`SudachiError: Invalid description: V0 version`）。実行時ダウンロード辞書を使う限り `>=0.6.0,<0.7.0` に固定

## 残存課題

- **any-term 3 クエリ（日本語 OR・一般語）の MRR が低い**（baseline 0.0 → 修正後 0.144）。all-term gold が存在しないクエリの正解判定が難しく、計測方法の改善も含めて継続課題
- sudachipy 0.7.x 対応（辞書の新形式移行 or 読み込み対応）
- rerank を有効化したい場合の高速化（ONNX 量子化等）
- グラフ信号（H6）の寄与の継続観測
