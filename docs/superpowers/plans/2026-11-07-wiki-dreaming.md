# 計画書: ドリーミング (wiki 整理) — 記憶の整理先を「まとめ wiki」へ

- 日付: 2026-11-07
- 関連: `2026-11-07-active-memory-pi-hook-and-freshness.md`（hook 抽出 + 鮮度評価）
- kanban: #13 (本書+レビュー), #14 (storage), #15 (worker), #16 (検索統合), #17 (MCP ツール), #18 (検証+デプロイ)

## 1. 背景

現在の nous の「オフライン統合」は:

- **DecayWorker** — FSRS 機械的減衰（忘却曲線）
- **ConsolidationWorker** — archived 記憶の gist 統合（semantic 層に要約ノードを作る）
- **FreshnessWorker** — LLM が記憶1件ずつ「まだ有効か」を判定（valid_until/superseded）

これらは「記憶を個別に検証・圧縮する」層であり、**記憶同士の関係を人が読める形に編纂する層が無い**。検索は毎回生の記憶断片を返すため、矛盾する断片が同時にヒットし得る。

Anthropic の "The components of agent memory" (2026, research) は、この編纂層を **dreaming** として定式化している:

- dreaming = オフライン（idle 時間）に transcript を読み直し、記憶を修正・再表現する処理（sleep-time compute / Letta, arXiv:2504.13171）
- 代表的な成果物 = **wiki**（Karpathy パターン, gist 442a6bf5）: 主題ごとのページ + 相互リンク。リンク自体が「記憶を辿る地図」になる
- 実測効果: 検索単独 53% → 検索+wiki 61%（wiki 成長に伴い 54%→61%）。**検索と併用して最も効く**（wiki 単独では 48%）。1問あたり ~20k トークン節約
- wiki が効くのは複数文書横断・判断が要るタスク。単一文書から検索で足りるタスクでは利得なし
- 失敗例: 詳細すぎる wiki は原文より大きくなる（Borges の地図）→ 抽象化しない wiki は無意味
- 上位層（毎セッション注入される索引）は**小さく保つ**ことが dreaming の仕事の半分（Claude Code auto memory は MEMORY.md の先頭 200 行 / 25KB だけ読む）
- リンク切れ修復・索引ページ追加も dreaming の役割
- 目標特化: 指示の調整で wiki の質が変わる（契約条項 wiki の 72% → 100%）

ユーザー要求（2026-11-07）: 「記憶の整理先をまとめ wiki にする」「検索しやすさも矛盾もなくなりそう」「DB あればベクトル検索できるよね？且つファイルベースで記憶ツールを拡張して grep/edit/ls とか基本的なファイル操作もできるようにしたらよさそう」「整理単位は project タグ × トピック」。

## 2. 設計方針（決定）

| 決定 | 内容 | 根拠 |
|---|---|---|
| wiki の実体 | **Markdown ファイル** `{DATA_ROOT}/persona/{persona}/wiki/{slug}.md` が正。DB `wiki_pages` は索引（ベクトル検索・一覧・リンクグラフ用）で、ファイルから再構築可能 | 人が読める・grep できる・git-ignored なので repo を汚さない。DB は検索の反映先 |
| 整理単位 | `project:<slug>` タグ × トピック。project 無し記憶は `persona:<p>` / `topic:<t>` ページへ | kanban #12 で全 memory に project:* が付くようになった。tag は既に検索文脈を持つ |
| 索引ページ | `index.md` を worker が自動維持（全ページ 1 行リンク+要約）。**小さく保つ**（ページ数上限・要約 1 行） | Anthropic: 上位層は小さいほど効く |
| 検索統合 | wiki 本文も埋め込みし、`memory_search` / `/api/search` の結果列に `source="wiki"` として合流（**検索が主、wiki が補助**の順位付け） | Anthropic: 検索併用時が最高。矛盾時は wiki（編纂済み）を上位に |
| エージェント操作 | MCP に `wiki_ls/read/grep/write/edit/rm` を追加。persona の wiki ディレクトリ内に閉じる（path traversal 拒否） | ユーザー要求。エージェントが直接編纂・参照できる |
| worker 分担 | freshness=「記憶1件の検証」専任 / wiki_worker=「整理先ページの維持」専任。consolidation は gist 生成のまま | 責務を混ぜない |
| 実行 | 既定 disabled。`NOUS_WIKI__ENABLED=true` で有効。周期 cycle + 手動トリガ API。監査は session_events (`wiki.updated`, `wiki.dream`) | 既存 worker と同じ安全規約（既定 off で副作用なし） |

## 3. データモデル

### 3.1 ファイル（正）

```
data/persona/herta/wiki/
  index.md                 # 自動維持。全ページの 1 行リンク+要約
  project-nous.md          # project:nous の総合ページ
  project-nous/memory.md   # トピック分割（サブディレクトリ可）
  persona-herta.md
  topic-memory-systems.md
```

frontmatter (YAML ではなく単純 key: value 行で最小実装 — パースを自前で持たない):

```
---
title: NOUS プロジェクト記憶整理
project: nous
updated: 2026-11-07T18:00:00+09:00
sources: memory_a, memory_b
---
本文 … [[project-dotfiles]] へのリンクは wikilink 形式
```

- 1 ページ上限 8KB（超過は**旧ページを保持** + 監査 + 次 cycle で分割。切り詰めない — 静かな知識欠落を許さない）
- 1 ページ上限のもう一次元: `max_sources_per_page = 40`（記憶本数で分割を強制。Borges 地図回避の構造的対策。プロンプト努力に依存させない）
- slug 規約: `[a-z0-9][a-z0-9_-]*` を `/` で結合（最大 3 階層）。**`:` は使わない**（Windows のファイル名で不正。記憶側の `project:nous` タグとは別名前空間で、ページ slug は `project-nous`）

### 3.2 DB 索引 — **v1 では作らない**

索引テーブル `wiki_pages` はファイル frontmatter と qdrant payload から全再導出できる二次キャッシュで、v1 の消費者が存在しない（検索は qdrant、一覧はファイル走査、O(N) でも数百ページ規模）。oracle レビュー指摘 #5 により**保留**。

再導入の条件（この時点で migration を作る）:
- ページ数が 500 超になりファイル走査が遅くなった
- ファイルと検索索引の drift 検出が必要になった
- wiki の一覧 API に SQL フィルタ（project 絞り込み等）が必要になった

それまでは **ファイル + qdrant（下記）のみ**。`:data:`store.py` の `rebuild_index()` は index.md（ファイル）の再生成であり、DB とは無関係。

### 3.3 ベクトル索引

- `QdrantVectorStore(collection_prefix="wiki_")` を新設 → `wiki_{persona}` コレクション。payload: `{slug, title, project, body_hash}`。point id は slug の安定ハッシュ
- **同期/非同期の分離**: `WikiStore` は同期なファイル層、`WikiVectorIndex`（新規、async）が embed + qdrant upsert を担う。worker は `asyncio.run()`、MCP/HTTP は `await`（`QdrantVectorStore.upsert` は async）
- `body_hash` は `title+body` から計算（render 後の全文だと `updated` の変化で毎 cycle 再 embed になる）

## 4. コンポーネント

### 4.1 `nous/infrastructure/wiki/store.py`（#14、実装済）

同期のファイル層（実装は既にこの通り）:

- `WikiStore(data_root, persona)`:
  - `list_slugs()` / `list_pages(include_index=False) -> list[WikiPage]`
  - `read_page(slug) -> Result[WikiPage, WikiStoreError]`
  - `write_page(slug, title, body, project, sources) -> Result[WikiPage, ...]`（原子的書込 + 8KB 拒否 + index.md 再生成）
  - `delete_page(slug)`
  - `grep(pattern, limit=50) -> list[(slug, line_no, line)]`（index.md は対象外）
  - `dangling_links() -> dict[str, list[str]]`（修復は worker 側）
  - `rebuild_index()`（index.md 再生成のみ。上限 `MAX_INDEX_LINES=120` 行で他分は「… +N more」に畳む）
- `parse_page` / `render_page` / `extract_links` / `page_hash(title, body)`（embedding 変化検知用）
- path 境界: `_validate_slug` + `_path_for` の `resolve().is_relative_to(root)`

### 4.2 `nous/application/workers/wiki_worker.py`（#15）

FreshnessWorker と同じ thread + `run_cycle()` パターン。1 cycle:

1. **整理対象の決定**: `project:*` タグの頻度上位 + **source 腐敗ページ**（下記）+ 未編纂記憶から topic を 1〜3 個選ぶ。
   **slug 同一性の不変条件**: slug = `{project}-{正規化topic}`。編纂前に**既存ページを title/project で照合して再利用**し、新 slug を作った場合は監査に理由を残す（cycle ごとに別 slug の重複ページが増えるのを防ぐ）
2. **材料収集**: 対象 topic の記憶のみ (最大 `max_memories_per_topic`、`max_sources_per_page` 超は分割対象)。**session_events は v1 の材料に含めない**（`sources` は実在 memory key のみ受理する契約と矛盾するため）
3. **LLM 編纂**: 既存ページを read → 「追記・修正・統合・矛盾解消」。出力は **ページ全体置換**（部分パッチは複雑度に見合わない）。上書き事故は**履歴**で守る: 書込前に旧ページを `wiki/.history/{slug}/{ts}.md` に退避
4. **検証**: wikilink 解決試行、`max_sources_per_page`、80KB/8KB 上限、sources が実在 memory か確認
5. **適用**: WikiStore.write_page/delete_page + `WikiVectorIndex.upsert` + 監査 `wiki.updated`
6. **索引維持**: `index.md` 再生成 + dangling link 修復（実在ページへ repoint、無理ならリンク削除）

**source 腐敗検出（freshness との責任分担）**: freshness が記憶を `archived`/`superseded` にしても wiki ページの主張は古いまま残る。wiki_worker の選択段に「`sources` のいずれかが active でない、または `memory.updated_at > page.updated` のページ」を追加し、最優先で再編纂する。

settings: `WikiConfig{ enabled=false, interval_seconds=86400, topics_per_cycle=2, max_memories_per_topic=40, max_sources_per_page=40, max_page_bytes=8192, provider/api_key/model は freshness と同型 }`

LLM はモデルに深さを持たせる（既定 `openrouter/openai/gpt-4o-mini` 相当の軽量 + reasoning モデル互換の max_tokens=8192）。

失敗時: ファイル書込をしない（fail-safe）。書込は tmp + rename で原子的に。

### 4.3 MCP ツール（#17）/ api/mcp/_tools_wiki.py

- `wiki_ls()` — slug, title, project, sources 数, updated_at
- `wiki_read(slug)` — 本文全文
- `wiki_grep(pattern, slug_prefix?)` — 行ヒット。**`asyncio.to_thread` で逃がす + pattern 長上限 200 字**（LLM 由来の regex でイベントループを止めない）
- `wiki_write(slug, title, body, project?)` — 新規/上書き（`WikiVectorIndex` も更新）
- `wiki_edit(slug, old_string, new_string)` — exact replace（edit ツール相当。不一致はエラーで返す）
- `wiki_rm(slug)`
- パス解決は **WikiStore のメソッドだけを使う**（`_resolve_wiki_path` を MCP 側に新設しない — 境界チェックを二重実装しない）。`index.md` は read のみ（store が書込を拒否）

### 4.4 検索統合（#16）

#### API 形（oracle 指摘 #1 で確定）

既存列は不変、wiki は別枠。

- REST `/api/search/{persona}`: `results[]` は**一切変えない**（`{memory, score, source}` のまま）。トップレベルに `wiki: [{slug, title, project, excerpt, score}]` を追加（0〜3 件）
  - 理由: `scripts/eval_real_queries.py:161` が `x.get("memory", {}).get("key")`、`nous/api/mcp/_tools_memory.py:508-511` が `sr.memory.key` を前提にしており、`memory: null` を混ぜると**既存ハーネスが AttributeError で全滅**する
- MCP `memory_search`: `memories` 配列は不変、`wiki[]` を追加
- 順位混合（`wiki_boost`）は**やらない** — 配列で順序は表現でき、測定前の閾値調整に根拠がない
- wiki 検索は `wiki_{persona}` qdrant + ファイル走査 TF のフォールバック。同一 slug は 1 件
- **上位層昇格（#16 で 1 行だけ前倒し）**: `nous/api/mcp/_tools_helpers.py:597-607` の PROJECT MEMORIES 節に `wiki: project:{slug} (n pages) → [[wiki-project-{slug}]]` を 1 行追加（既存の `_MAX_TOTAL_CHARS` 予算内）
- recall push (pi hook) は当面 memory のみ

## 5. リスクと対策

| リスク | 対策 |
| --- | --- |
| wiki が原文より肥大（Borges 地図） | ページ 8KB + `max_sources_per_page=40`（記憶本数で分割強制） |
| worker が幻覚で矛盾ページを作る | sources 必須（実在 memory key のみ受理）、旧ページを `.history/` に退避して置換、監査行で差分追跡 |
| freshness と wiki の責任の空白 | wiki_worker 選択段に source 腐敗検出（archived/superseded/memory newer）を最優先で追加 |
| slug の増殖 | slug=`{project}-{topic}` + 編纂前の既存ページ照合を不変条件に。新 slug は監査に理由を記録 |
| embedding コスト増 | `body_hash`（title+body）で変化時のみ upsert。cycle は topics_per_cycle で上限 |
| grep の ReDoS | `to_thread` + pattern 長 200 字上限 |
| 検索 API 互換 | `results[]` / `memories` は不変、`wiki[]` を追加のみ（eval ハーネス・pi 拡張が読む形を壊さない） |
| index.md 肥大 | `MAX_INDEX_LINES=120`、超分は「… +N more」に畳む |

## 6. 段階計画（kanban）

1. **#14** store.py（ファイル層、実装済/完了）+ 単体テスト
2. **#15** wiki_worker + WikiVectorIndex + settings + main.py wiring + 手動トリガ + テスト（LLM はモック）
3. **#16** 検索統合（`wiki[]` 別枠）+ PROJECT MEMORIES 1 行 + テスト
4. **#17** MCP wiki ツール + traversal/ReDoS テスト
5. **#18** 統合: pytest/ruff/mypy-baseline → oracle コードレビュー → Docker build → stack 37 redeploy → 本番実測

## 7. 検証

- 単体: store（write/read/delete/grep/link repair/index 上限）, worker（prompt 生成・JSON parse・fail-safe・監査行・source 腐敗選択）, tools（traversal 拒否・edit 一致不一致）
- 統合: 本番 Data で wiki_worker を手動実行 → ページ生成 → `memory_search` の応答に `wiki[]` が出る
- 回帰: 既存 pytest 一式 + **`scripts/eval_real_queries.py` / `tests/unit/test_http_api.py`**（API 形の破壊検出）+ ruff + mypy-baseline
- 事前実測: 本番 DB の `project:*` タグ付与率（#12 は新規書込みのみ。既存記憶の付与率が低ければ #15 のクラスタ設計が成立しない）
