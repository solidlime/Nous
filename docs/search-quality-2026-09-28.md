# 記録: 記憶検索精度の改善（日本語 OR 検索・semantic 死亡・recency 逆転の修正）

- 日付: 2026-09-28
- コミット: `f6e773a0` fix(search): RankPolicy を MCP/REST に配線し重みを統一（順位の経路間不一致を解消）/ `d6c45cd7` fix(search): semantic 復活・rerank 範囲制限・recency タイブレークで検索精度を改善 / `02a691af` test(bench): 検索品質の評価ハーネスと検証用 Dockerfile / `c4dc534d` fix(ci): CI 赤の4原因を修正 / `2e77da88` fix(deps): sudachipy を <0.7.0 に固定
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

> **計測時の注意**: HTTP API の `q` に生の日本語を渡すと h11 が request line を拒否する（`Invalid HTTP request received.`）。`curl --get --data-urlencode 'q=...'` を使う。

## 実装（修正1〜10）

| # | 内容 | 主なファイル |
|---|---|---|
| 修正1 | semantic 復活（`search_engine` の二重定義解消・`is_loaded` ガード修正） | `nous/application/context/vector_stack.py` |
| 修正2 | H6: グラフ信号の本番経路有効化 + 候補の再 encode 排除 | `nous/domain/search/engine.py`, `policy.py`, `vector_stack.py` |
| 修正3 | `SearchConfig.rerank_enabled=False`（既定無効化）+ `keyword_weight` 0.5→1.0 | `settings.py`, `engine.py`, `ranker.py` |
| 修正4 | MCP/chat の `keyword_weight` 既定を 1.0 に統一 | `mcp/tools.py`, `_tools_memory.py`, `definitions.py`, `ranker.py` |
| 修正5 | recency 既定値の統一（暫定 0.0） | 同上 |
| 修正6 | **recency を相対（乗数）方式のタイブレークに変更**。`adjusted = rrf_score * multiplier`（`multiplier` は 1.0 起点で importance/recency をスケール）。既定 0.05 を HTTP/MCP で統一 | `ranker.py`, `settings.py`, `engine.py` |
| 修正7 | **F1: RRF 統合時に勝者候補の付加フィールド（`cosine` / `lexical_score` / `similarity_flag`）を引き継ぐ**。これを落とすと rank_policy 段の relevance/lexical 項が構造的に 0 になり composite がデッドコード化する | `ranker.py` |
| 修正8 | MCP `memory_search` と REST `/api/search/{persona}` に **RankPolicy（composite ランキング）を配線**（従来は chat 経路のみで、両 API 経路は RRF 順位のままだった） | `_tools_memory.py`, `search.py`, `engine.py` |
| 修正9 | 候補の**再 encode を排除**（ベクトル再利用。semantic 候補の cosine を RRF 統合後もそのまま使う） | `engine.py`, `vector_stack.py` |
| 修正10 | REST/MCP の重みを `RankPolicy.from_weight_args` で**統一**（REST はクラス既定 0.25 → MCP と同じ 1.0 に）。両経路の順位が完全一致することをテストで保証 | `policy.py`, `search.py`, `_tools_memory.py` |

全て追加的・後方互換（DB スキーマ無変更、MCP スキーマ互換）。

## ベンチ結果（before/after）

評価ハーネス: `tests/benchmark/` + `scripts/eval_search_quality.py`（12 クエリ）。**表中の値は全て実 artifact の JSON から転記**しており、各行の出典を artifact 列に明記する。

| 実行 | 状態 | zero-result | recall@5 (AT 9件) | MRR (ALL 12件) | MRR (AT 9件) | p95 latency | artifact |
|---|---|---|---|---|---|---|---|
| baseline_v1 | 本番（semantic 死、top_k=20） | 3 | 0.668※ | **0.750** | 1.0000 | —（中央値 0.677s） | `baseline_v1.json` + `baseline_v1.md` |
| verify_v1 | 修正1（rerank 有効） | 0 | 0.555 | —（any-term 未計測） | 0.8312 | 8.4s（rerank 有効） | `verify_v1.json` |
| verify_v2 | 修正1〜2 | 0 | 0.9259 | —（any-term 未計測） | 0.8704 | — | `verify_v2.json` |
| eval_v3_warm | 修正1〜4 | 0 | **0.9815** | —（any-term 未計測） | 0.8704 | **0.097s** | `eval_v3_warm.json.json` |
| final_v3_mcp_verify_warm2 | 修正1〜6（MCP, 暗黙 top_k=5） | 0 | **0.9815** | 0.8611 | 1.0000 | 0.238s | `final_v3_mcp_verify_warm2.json.json` |
| **final_v5_mcp_quiet** | **＋重み統一（MCP, top_k=20, 無負荷）** | **0** | **0.9815** | **1.0000** | **1.0000** | **0.366s** | `final_v5_mcp_quiet.json.json` |
| **prod_final_v1** | **本番デプロイ後（commit 96307d17）** | **0** | **0.9815** | **0.8611** | **1.0000** | **0.174s（REST）/ 0.310s（MCP）** | `prod_final_v1.json.json`（REST）/ `prod_final_v1_mcp.json.json`（MCP） |

**指標定義**: `recall@5 (AT)` と `MRR (AT)` = all-term gold（全語を含む記憶。9 クエリで計測可）。`MRR (ALL)` = any-term gold（いずれかを含む記憶。全 12 クエリ）。**合格ライン（案C）の MRR 判定は ALL（全 12 クエリ）で行う**。「—（any-term 未計測）」はハーネスに any-term 指標を追加する前の測定 artifact であることを示す。

**※ baseline_v1 の基準について**: この artifact はハーネスに AT/any-term 別指標を追加する前の測定であり、`recall@5` は **any-term gold に対する値**（9 件で 0.668、12 件で 0.501）。`baseline_v1.md` の集計（r@5 0.547 / MRR 0.818）は **generic_np を除く 11 件** の値で、rows から再計算した値（MRR 0.8182 / r@5 0.546）と一致する。**以降の行の `recall@5 (AT)` とは基準が異なる**ため、before/after の同一基準比較は **verify_v2 以降の行同士**で行うこと。

- **recall@5: 0.501（baseline 全 12 件）→ 0.9815**（AT 9 クエリ、新ハーネス）※ 基準が異なるため参考値
- **MRR (ALL): 0.750 → 本番 0.8611**（12 クエリ全件。検証環境の最良値は 1.0000）
- **MRR (AT): 1.0000 → 1.0000**（baseline 時点で既に top1 は取れていた = MRR の弱点は any-term 側だった）
- **p95: 8.4s（rerank 有効時）→ 本番 0.174s（REST）**
- 合格ライン（案C、**ALL 基準**）: **zero-result 0 ✅ / recall@5 0.9815 ≥ 0.75 ✅ / MRR 0.8611 ≥ 0.80 ✅ / p95 0.174s ≤ 1.5s ✅**（本番実測値。詳細は「本番デプロイ後の合格ライン判定」節）

### 実クエリ 130 件（search_log 頻度順、検証環境 nous-verify2）

| 実行 | 経路 | zero-result | MRR | p5 | artifact |
|---|---|---|---|---|---|
| 修正前（本番） | REST | 0 | 0.9324 | — | `lexical_ab_analysis.md`（測定2） |
| 配線直後（lexical 0.25） | REST | 0 | 0.9056 | 0.7776 | （§監査指摘への対応参照） |
| **重み統一後** | **MCP** | **0** | **0.9577** | **0.8144** | `artifacts/real130_after_mcp.json` |
| **重み統一後** | **REST** | **0** | **0.958** | **0.8095** | `artifacts/real130_after_rest.json` |

**測定条件（MCP/REST 共通）**: 検証コンテナ `nous-verify2` の内部から `http://localhost:26262`（Host ヘッダ `localhost:26262`）に接続。検証 DB（`/data/persona/herta/memory.sqlite` = 本番コピー）と検証 Qdrant（1024 points 時点）を使用。コードは main `f6e773a0` 相当。`--limit 130 --top-k 10`、無負荷、2026-09-28 17時台 JST。score 対象は 130 件中 MCP 125 / REST 126（全語が DB に存在しないクエリは skip）。両 artifact の summary に `note` / `commit` / `top_k` を記録済み。MCP/REST の僅差（0.9577 vs 0.958）は検証 Qdrant のコピー時点差と skip 数差によるもので、**経路間の重みは `tests/unit/test_mcp_rest_rank_policy_wiring.py` が同一であることをテストで保証**している（`RankPolicy` の frozen dataclass 等価）。

- 注1: `p95 8.9s` の測定値が一時記録されたが、これは並行実行した mypy/pytest との **CPU 競合**（Celeron 4 コア環境）が原因。無負荷の再測定では 0.366s。
- 注2: ハーネス `mcp_search` が `"limit"` を送っていた過去バグ（正しい引数は `"top_k"`、pydantic が黙って無視）のため、MCP 経由の過去測定は常に暗黙 top_k=5 だった。修正後は明示 top_k が効く。

### 監査指摘への対応状況（2026-09-28 再実測）

**指摘1（合格ラインのメトリクス切り替え）**: 合格ラインの MRR 判定を **ALL（any-term 全 12 クエリ）** に統一して再評価。検証環境で **ALL MRR 1.0000**、本番デプロイ後も **ALL MRR 0.8611**（≥ 0.80、後述の「本番デプロイ後の合格ライン判定」参照）。AT 値（1.0000）も併記しており、狭い方の指標のみでの主張はしない。

**指摘2（再現可能な artifact）**: 上表の artifact 列の通り、各実行の JSON を `research/nous-search-eval-20260928/` に保存。実クエリ 130 件も `artifacts/real130_after_mcp.json` として保存済み。

**指摘3（`VRM 照明` の top1 主張）**: 2026-09-28 に再実測（top_k=5、MCP 経由）:
- **本番（旧コード、RankPolicy 配線前）**: top1 = `memory_20260928131831_782616_3b7207a8`（task-5 の自己記録）、元 gold `memory_20260915014126_130820_0140fb35` は **2 位**
- **検証（重み統一後、配線済み）**: top1 = **元 gold**（2 位 = 別の照明関連記憶 `memory_20260915020641_093119_91c26cd7`）

task-4 時点の「gold top1」はその時点では正しかったが、task-5 で自己記録記憶が追加されたことで本番では 2 位に変化した（自己記録の内容が「nous 検索精度改善」でありクエリ語と強く重なるため）。**デプロイ後の本番（コンテナ `4fafbfdf9c87`、commit `96307d17`）で再実測した結果、top1 = 元 gold `memory_20260915014126_130820_0140fb35` に戻ったことを確認**（2 位 = 自己記録記憶）。配線（`f6e773a0`）により relevance 項が本番経路でも正しく順位に反映されるようになったことが直接の原因。

### 本番デプロイ後の合格ライン判定（2026-09-28 17時台、コンテナ `4fafbfdf9c87`）

**測定条件**: pi コンテナ（ホスト）から `http://nas:26262` に接続。**本番 DB（4204 件）+ 本番 Qdrant（1026 points）**。top_k=5、無負荷、commit `96307d17`（コードは `f6e773a0` と同一）。REST は `--transport http`、MCP は `--transport mcp --host-header localhost:26262`。

| 指標 | REST | MCP | 合格ライン（案C） | 判定 |
|---|---|---|---|---|
| zero-result | 0 / 12 | 0 / 12 | 0 | ✅ |
| recall@5（AT 9クエリ） | 0.9815 | 0.9815 | ≥ 0.75 | ✅ |
| MRR（AT 9クエリ） | 1.0000 | 1.0000 | ≥ 0.80 | ✅ |
| **MRR（ALL 12クエリ、any-term）** | **0.8611** | **0.8611** | **≥ 0.80** | ✅ |
| hit@5（any-term 12クエリ） | 0.9167 | 0.9167 | — | — |
| p95 レイテンシ | 0.174 s | 0.310 s | ≤ 1.5 s | ✅ |
| 症状実例 ja_or_001〜005 | 全て MRR 1.000 | 同左 | 全件合格 | ✅ |

- artifact: `research/nous-search-eval-20260928/artifacts/prod_final_v1.json.json`（REST）/ `prod_final_v1_mcp.json.json`（MCP）
- 再現コマンド（REST）: `uv run python scripts/eval_search_quality.py --transport http --base-url http://nas:26262 --persona herta --limit 5 --corpus /root/workspace/research/nous-search-eval-20260928/herta_corpus.json --queries tests/benchmark/data/search_quality_queries_v1.json`（MCP は `--transport mcp --host-header localhost:26262` を追加）
- **REST と MCP の全指標が完全一致**（RankPolicy 配線が本番で有効に働いている直接の証拠）
- 監査指摘「ALL MRR 0.762（再計算）」は**解消**: 配線 + lexical_score 引き継ぎ（`f6e773a0`）により ALL MRR **0.8611** へ改善（≥ 0.80）。
- 残る弱点: `generic_np_001`（「確認 お願い」型の一般語 1 語クエリ、gold 291 件）のみ any-term MRR 0.000（top5 に gold なし）。**一般語 1 語では順位信号が本質的に弱い**ため、これは残存課題として明記する（§残存課題）。

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
   - 実検索: `curl --get --data-urlencode 'q=VRM 照明' --data 'limit=5' http://nas:26262/api/search/herta` → 正解記憶が上位に返る
     - **注意**: URL に生の日本語を入れると h11 が `Invalid HTTP request received.` で拒否する。`--data-urlencode` かパーセントエンコード（`q=VRM%20%E7%85%A7%E6%98%8E`）を使うこと

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

- **一般語・抽象語の複合クエリ（日本語 OR 含む）**: 実クエリ 130 件で gold を top5 に入れられないのは 3 件（`睡眠時 記憶統合 深眠 タグ整理` MRR 0.000 / `機能確認テスト` 0.125 / `queued 処理` 0.250）。残り 5 件は MRR 0.333〜0.5（gold が 2〜4 位）で実用上は許容。修正前は低 MRR 17 件だったので大幅に改善しているが、語彙の重なりが弱い一般語クエリは継続課題。**合成セットの `generic_np_001`（「確認 お願い」、gold 291 件）も同型で、本番 any-term MRR 0.000**（top5 に gold なし）。一般語 1 語クエリは順位信号が本質的に弱く、top1 の意味が薄い（gold 集合自体が広すぎる）ため、指標の性質として限界を明記する。
- sudachipy 0.7.x 対応（辞書の新形式移行 or 読み込み対応）
- rerank を有効化したい場合の高速化（ONNX 量子化等）
- グラフ信号（H6）の寄与の継続観測
