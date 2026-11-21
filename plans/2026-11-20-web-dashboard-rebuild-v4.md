# webダッシュボード v4 フル刷新計画 — SSR+vanilla維持 / API含む

date: 2026-11-20
prev: plans/2026-11-20-dashboard-mission-deck.md (#126) / plans/2026-11-20-webui-mission-deck-unification.md (#127)
goal: Nous Dashboard を1から作り直す。API含む。SSR+vanilla踏襲。モバイル・150ms・見た目を全部叶える。

## 0. ユーザー回答（m00029）の確定事項
- 対象: Nous Dashboard（このrepo）。pi-kanban-boardではない
- 範囲: API含めフル刷新（/api/dashboard 等の再設計可。互換期間あり）
- 技術: 現行踏襲 SSR+vanilla（React/Vite化しない。単一HTML集約でもない）
- 最優先: 1,2,3全部（モバイルで使える / 150ms / 見た目一新）

## 1. 現状把握（EXPLORE済み・実測値）
- `nous/api/http/static`（node_modules除く）142ファイル・合計4.5MB
  - 犯人: `three.core.js` 1.4MB + `three.module.js` 603KB + `vendor/lucide.min.js` 497KB + avatar系 ~400KB + `graph.js` 70KB + `chat.css` 56KB + `components.css` 43KB + `sections.css` 38KB
  - 初回クリティカルパス: CSS 9本link + JS 50本超 `<script defer>` + CDN 6本（chart.js / vis-network / vis-timeline×2 / marked / dompurify / Inter font）。リクエスト数だけで150msは不可能
  - `render_layout_shell` は9タブ全HTMLを一括SSR。`main-content` に overview〜settings まで全部入り
- API: `GET /api/dashboard/{persona}`（persona_dashboard.py `_do_dashboard_data`）が全部入り
  - stats + context + recent(50件フル) + blocks + equipment + items + goals(最大30) + rel_highlights(10) + state_memories + generated_images(20) + prompt enrichment（`SELECT metadata FROM messages WHERE metadata LIKE '%image_generation%'` 全走査）
  - 画像20件・recent50件で数十〜数百KB。KPIだけ欲しい Overview 初回に過剰
- 契約（壊すとテストが落ちる）
  - `tests/unit/test_wiki_router.py:214-231` — `class="tab-btn..."` 先頭一致 + `data-tab` / `data-loader` / `data-loader-args="[true]"` / `data-self-managed` / `aria-selected` の書式・順序
  - `static/chat/chat-wiring-feed.test.js:256-267` — components.css の `.ov-modal{...var(--bg-secondary)}` 存在・`.ov-field` の rgba直書き禁止・`.wiring-kind-link_fire` の `--accent-purple-rgb` 存在
  - `tests/integration/test_dashboard_e2e.py` — `/` に9タブ名・`/static/styles/` link・dashboard JSONキー（persona/stats/context/recent/blocks/equipment/goals）
- モバイル: #127で768px単一化済み。残課題は登録UI（memories追加がtextarea頼み・touch target小）・モーダル全幅・cmdbar被覆・chat入力溢れ
- 見た目: Mission Deck語彙（glass変数・細線3px・mono数字）は #126/#127 で確立。これをSSOTとしてv4に継承。新語彙の発明禁止

## 2. 方針（フル刷新でも守るもの）
1. SSR+vanilla・`N.*` 名前空間・delegation（`data-action`）・skeleton契約（`:scope > [id$="-content"]`）は維持。React化しない
2. Mission Deckトークン（variables.css + sections.css:511-668相当）をSSOTに継承。新色・新変数の発明禁止（`--veil-*` 残置方針も継承）
3. 契約テストを先に固定してから壊す。属性書式・CSS直読み・dashboard JSONキーは v1 で温存し、v2 を並行追加→移行→旧削除の順
4. 速さは「削って勝つ」。追加で速くしない。three/avatar/CDNを初期パスから外すのが主砲
5. 1ファイル1人形。commit/pushは統括のみ。人形にさせない

## 3. アーキテクチャ（v4）
### 3.1 シェル痩身（初回150msの本体）
- `render_layout_shell` を v4 shell に: `<head>` は critical CSS 2本（`shell-critical.css` + `theme` 変数のみ）+ `shell.js` 1本のみ。50本のdefer・CDN・Inter・lucide直読みを初期から外す
  - lucide は遅延。`static/` 配下の `lucide.createIcons()` 直呼び29箇所（vendor・core/dom.js除く実測。コメント1行含めると30）は全て `typeof lucide` ガード付きであり、新規ReferenceErrorリスクは無い。`core/dom.js:18-28 N.Core.refreshIcons`（rAF合体＋再ガード）へgrep置換で寄せるのが目的は、lucide未ロード時の取りこぼし（`timeline.js:49,94,136` のsetTimeout経由）を潰すこと（M4修正）。人形Aが単独で先行
  - `three/*` `avatar/*` `chart.js` `vis-*` `marked` `dompurify` はタブ要求時の動的loadのみ
- `render_dashboard` は9タブ全SSRをやめる。初回は `#tab-overview` の骨格（crumbs/persona/KPIスケルトン）のみSSRし、残り8タブは **content divのみの空section**を原則とする（`<section id="tab-X"><div id="X-content"></div></section>` をSSRで必ず吐く。中身は空）。ただし自己管理タブ（wiki/projects/chat/activity/timeline/graphの6タブ。dashboard.py:38-75実測）は `-content` 有無がper-tabで異なる現行契約を維持する——`skeleton.js:43-55` 契約(a)が「content-lessパネルは自前DOM管理・renderNoPersonaはパネル根にフォールバック禁止」と定め、`base.test.js #93` が `tab-activity` に `-content` が無い前提で「パネル根を壊さない」を回帰保証しているため。全9に機械的に付けると `renderNoPersona` が自己管理タブを空ステートで上書きする新経路が生える（B1-a）。実測per-tab: projectsはselfManagedかつ `<div id="project-content">` あり（projects.py:22）、graphはselfManagedかつ `<div id="graph-content">` あり（knowledge_graph.py:51）。よって回帰assertは **非selfManagedの3タブ（overview/memories/settings）に限定**し、自己管理タブは現状有無をper-tab実測どおりassertする（`:scope >` 直下限定と整合）。空`<section>`だけ（content div無し・非selfManaged）は禁止——`skeleton.js:56-58 panelContentEl` が `:scope > [id$="-content"]` を要求し、無いと `:95` パネル根フォールバックでパネルごとスケルトン化＋`renderNoPersona(base.js:44-49)` 無反応になる（B1）
- `render_nav` の属性書式は1文字も変えない（_wrapper追加のみ可。`.tab-bar` クラス維持・`buildHamburgerMenu` 依存を守る）
- 遅延してもe2eの文字列assertを落とさない: `test_dashboard_e2e.py:210`（chart.js）と `test_wiki_router.py:199`（/static/features/wiki.js）対応として、SSRに遅延manifest（`lazy-manifest.json`相当のchunk一覧）を埋め込み、両文字列がHTMLに残る形にする。manifestが遅延ロードのSSOTも兼ねる。e2eをv2前提に黙って書き換えることはしない（B2・統括判断a案採用）
- chunk化の副作用対策: `settings-core.js:62-73`（switchTab後ラップ）・`projects.js:130-140`・`timeline.js:163-175`（main-contentへのMutationObserver）・`wiki.js:493`（DOMContentLoadedでrefreshWiki）はDOMContentLoaded依存のため、そのまま `import()` 化するとラップ順不定・初回オブザーバ不発・wiki永久不実行になる（B5）。対策として `shell.js` に `N.Core.whenReady(fn)`（readyStateを見る1関数）を置き、全chunkの初期化は `whenReady(init)` 経由に統一する規約とする。置換は機械的
- chunk manifestは `base.py` 内の1定数（or JSON1本）をSSOTとし、書くのは人形Aのみ。人形Cはchunk名を登録申請する（N1。Aが `styles/*`＋build、Cが `chat.css` を同時編集する衝突の防止）
- `md-cmdbar` は維持（⌘K→Chat遷移）。Chat・モバイルでは非表示（#126の `:has()` 手法を継承）
- 受け入れ: 初回HTML <30KB・critical CSS <20KB・critical JS <30KB・リクエスト数 初回10以下・CDNゼロブロッキング

### 3.2 CSS v4（2本に畳む）
- `shell-critical.css`（新規・variables+reset+layout+rail/header/cmdbar/toast/skeleton のみ）: 初回で読む唯一のCSS
- `tabs-lazy.css`（新規・components+sections+chat+chat-mobile を結合・minify）: Overview描画後 or idle時にpreload。タブ別分割はしない（分割管理コストが速度利益を上回る）
- 生成はビルド時結合（手書き結合体を repo に持たない。`scripts/build-css.mjs` 追加。nodeで連結するだけ。依存追加なし）。ただし `@layer` 制約を守る（B3）: (1) 層宣言 `@layer reset, base, ...` は出力の1行目のみ（variables.css:1とreset.css:1の二重出し禁止。2回目は無視される）、(2) `sections.css` 由来のunlayeredは必ず末尾に固定（sections/base.py:44コメント「sections.cssは必ず最後・unlayered」の契約。壊すとlayer済み全規則が負けて全タブ崩れ）、(3) 出力順を配列で固定しその配列をテストでassert。ビルド後に `@layer` 出現回数=1 をgrepで機械判定
- グローバル層（`.md-cmdbar` / `.toast*` / `.ov-modal*` / `.mem-modal*` / `.nav-drawer` / `.nav-backdrop`）は全部 shell-critical に固定（B4）。`.md-cmdbar` 実体は `styles/sections.css:635-668`（`body:has(#tab-chat.active)` の切替含む）であり、所属未定のままでは `layout.css:105-108 .tab-panel{contain:layout style paint}` がfixedのcontaining blockを作り #126の被覆修正が回帰判定できない。`base.py:256-258` の「`.tab-panel` の `contain: paint` がfixedを壊す」注記をコードで守る。分割基準に「モーダル/トーストはshell-criticalに含む」と明記し（N3）、FOUC時の全幅不発を防ぐ
- `.tab-head` 一本化・768px単一・z-indexトークン・モーダル全幅（≤767px）・`.md-*` 対応表は #127 を継承し、v4 CSSに移植

### 3.3 JS v4（shell.js + 動的import）
- `shell.js`（新規・`N.*` 互換）: namespace/store/dom/api/toast/sse/theme/base/delegation/skeleton のみ結合 ~30KB。`loadTab` は `import()` でタブ別 chunk を遅延取得
- タブ chunk: `overview.chunk.js` / `memories.chunk.js` / `chat.chunk.js` / `misc.chunk.js`（wiki/projects/activity/timeline/graph/settings）。現行ファイルを結合するだけで書き直さない（第1段階）。graph/chat の重い依存は chunk 内で遅延load
- `safeSetHTML` の `FORBID_ATTR style` 契約・`applyDataStyles[data-fill]` 方式は維持。`style=` 直書き禁止も維持
- vitest 38 files は chunk化後も緑（import path のみ更新。テスト内容不変）

### 3.4 API v2 slim（フル刷新的本体・互換期間あり）
- v1 `GET /api/dashboard/{persona}` は温存（e2e契約のため）。**v1のパラメータは1つも変えない**——recentの10件既定・`?full=1` はv2のみ。v1の `get_recent(limit=50)` に触るとOverviewのRecent表示が痩せる（M1）。v2 を新設し、v4 UIはv2のみ叩く
  - `GET /api/v2/overview/{persona}` → KPIのみ（memories_count/wiki_count/projects_count/linked_ratio/place_since/environment）。<2KB目標
  - `GET /api/v2/recent/{persona}?limit=10` → recent分页（10件既定・最大50）。full bodyは `?full=1` のときのみ（v2のみ）
  - `GET /api/v2/blocks|equipment|items|goals|images/{persona}` → 遅延ロード用に分割。images は prompt enrichment を別クエリ化（messages全走査をやめ `filename IN (...)` で20件に限定）。ただし `meta.get("type") != "image_generation"` フィルタとfilename重複時の後勝ち仕様はv1と同一結果であること。`test_v2_images.py` でv1と `filename/revised_prompt/negative_prompt` の完全一致を1本 assertする。`img.url` は `/api/chat/{persona}/persona/images/{name}` のまま `N.Core.auth.sign()`（#102）に通ること（M3）
  - portraitはoverviewに残さず imagesレスポンスに同梱する。portraitと画像一覧は同一ディレクトリスキャン由来であり、分離するとOverview初回で overview+images+recent+blocks+equipment+items+goals+wiki=8〜9reqになりChat初期化分で req≤10 を超過する（M2）。Overview初回は KPI→recent→images の3本までに上限固定
  - `GET /api/wiki/{persona}` はKPI流用で継続（#126手法）。`/api/observations` `/api/search` `/api/settings` は変更なし
- 移行後に v1 を thin wrapper（v2合成）にし、テストをv2に寄せてから旧実装削除。いきなり消さない

- `S.dashCache` をセクション別キャッシュ（`S.dashCache.overview|items|blocks|images`）にし、各ローダが必要キーだけ埋める（B6）。現行 `base.js:14,172,227` の全量前提＋`memories-core.js:82-85` の全量fetch＋`:227-228 tag_distribution` 直読み＋`overview-inventory.js:59-60 S.dashCache.items` 直読みのまま分割するとmemories/inventoryが空になる（e2eはdashboard JSONしか見ないので検出不能）。分割と同時に `memories-core.js:82-85` の全量fetchを `/api/observations?mode=recent` ベースへ寄せる（既存APIで足りる）

### 3.5 モバイル登録UI（textarea1個問題の解消）
- memories追加を `content(textarea) + tags(input/chip) + importance(range)` の3部品に。**`importance` は `nous/api/http/deps.py:27-36 CreateMemoryRequest` の実定義どおり `float = 0.5`・ge/le制約なし・サーバ側クランプ無し（`memory.py:254 body = CreateMemoryRequest(**raw)` で素通し。旧記述の `memory.py:243` は行ズレ）。サーバが弾かない以上、UIのrangeは 0.0–1.0・`step=0.05`・初期値0.5 を人形B側の裁量で決める旨を明記。推測で埋めない（N2実測反映）**。44px touch target・`enterで送信しない`・連打ガード。Tailscale+スマホ実機で登録→一覧反映までを検収項目に
- モーダル・toast全幅（≤767px）。chat入力欄 `min-width:0`・`min-height:0`・表 `overflow-x:auto`（#127の3点を継承）
- 360pxで横スクロールゼロ・9タブ全操作可をGATEに入れる

### 3.6 対象外（やらないと明言）
- React/Vue/Svelte化・Tailwind再導入・SSR→CSR完全移行・`--veil-*` 統廃合・`features/resonance.*` 救済・wiring/SSE再接続の根治（#127 drive-byは別カード）・TTS/voice改修

## 4. 担当分割（1ファイル1人形・衝突回避）
| 担当 | ファイル | 人形 |
|---|---|---|
| A: シェル+CSS | sections/base.py / dashboard.py / styles/* / scripts/build-css.mjs | #011-A（sections.cssはA単独） |
| B: タブ+API v2 | sections/*.py（base除く） / routers/persona/persona_dashboard.py + v2 routers / features/*.js（chat除く） | #011-B |
| C: チャット | sections/chat/* / chat/*.js / chat.css / chat-mobile.css | #011-C |
- 触ってはいけない共通: `tests/unit/test_wiki_router.py` の期待文字列・`chat-wiring-feed.test.js:256-267` のCSS契約・`render_nav` 属性書式。変えるなら統括判断
- commit/push・RECORDは統括のみ

## 5. TEST（機械判定）
1. pytest 全緑（tests/unit + tests/integration。新規 test_v2_overview.py 追加。pre-existingはstash実証で例外扱い）
2. vitest 全緑（chunk path更新後も38files/402tests維持）
3. `node --check` 全JS・CSS braces・未知変数ゼロ（variables実在のみ）・`max-width:768px`/`min-width:769px`/`<= 768` 残渣ゼロ
4. 初回性能: ローカル計測でHTML<30KB・critical<50KB合計・リクエスト≤10・`/api/v2/overview` <2KB・リロード→操作可能の実測を記録（150msはローカル目標。Tailscale越しは別計測で報告のみ）。計測条件を固定（M5）: (a) coldはサーバ再起動＋DevTools disable cache、(b) warmを別記、(c) `PerformanceNavigationTiming.responseStart→domContentLoadedEventEnd` を記録（目視ストップウォッチ禁止）。`nous/main.py:166-183` の `/static` はFileResponse直返しで Cache-Control/ETag/gzipが無いためcold/warmで桁が変わる。gzip/Cache-Control導入はv4スコープ外（やらない）と明示——4.5MBの `three.core.js` が無圧縮で流れる経路が残ることを既知とする
5. SSR smoke: 9タブのid・data-loader・見出しh2が変更前と同一。加えてDOM assert2本: (i) 非selfManaged 3タブ（overview/memories/settings）の直下に `[id$="-content"]` が1つ存在＋自己管理タブはper-tab実測どおり（projectsのproject-content・graphのgraph-contentあり、wiki/chat/activity/timelineは無し。B1-a。`base.test.js #93` と整合。`base.test.js:117-123` のactivityケースは維持）、(ii) `document.querySelector('.md-cmdbar').parentElement === document.body`（B4。目視では見落とす）
6. 契約: v1 JSONキー維持（e2e緑）+ v2 round-trip。`test_v2_images.py` でv1との `filename/revised_prompt/negative_prompt` 完全一致1本（M3）

## 6. 実ブラウザ検収（8793 / r127 fixtures流用・3幅×2テーマ）
1. 360px: 9タブ横スクロールゼロ・ハンバーガー・モーダル/トースト全幅・memories登録（3部品）→一覧反映
2. 768pxちょうど: レール表示・ハンバーガー非表示・チャットがデスクトップ（キメラゼロ）
3. 1024px: overview 2col・KPI4枚
4. light/dark両テーマで破綻ゼロ・バー全可視
5. Chat送信→応答→中止・cmdbar表示切替（Chatで非表示・他で表示）
6. Equipment/Inventory/Blocks CRUD 1導線以上・wiki編集保存・persona切替・テーマ切替・aria-selected単一
7. CDPスクショ + ネットワーク計測（初回バイト・リクエスト数）を記録

## 7. REVIEW→GATE→COMMIT→RECORD→PUSH
- 本計画書v4→ルアン・メェイ事前判断でBLOCK（B1〜B6・M1〜M5・N1〜N3）を反映しv4.1として再提出。PASS以外は着手しない
- GATE: 型pass / テスト失敗0 / カバレッジ≥60% / lint0 / format ok / 契約pass / シークレット0 / 監査≤moderate / ドキュメント同期 / 禁止操作なし
- COMMITは統括が1本にまとめる。RECORDは `project:nous`（task_state + decision）。PUSHまで

## 8. リスク
| リスク | 対応 |
|---|---|
| 9タブ遅延で初回スケルトン祭り | overview骨格のみSSR+スケルトン維持。残タブはhover/intent preload |
| v1/v2二重運用の負債 | v1をthin化→テスト寄せ→削除の3段。放置しない |
| 結合CSS/JSのデバッグ性低下 | build scriptは連結のみ（minifyは空白除去程度）。sourcemap無しでも読める範囲に |
| 150ms未達（特にTailscale越し） | ローカル150msをGATE、実回線は計測報告。削り残し（lucide/three/CDN）を先に削る |
| 人形並列の衝突 | §4分離厳守。同一ファイルは統括が直す枠に |
