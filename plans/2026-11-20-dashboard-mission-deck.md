# ダッシュボード刷新 実装計画 (Mission Deck / シック版) — 改稿7

## 決定事項
- ユーザー承認: A案 (Mission Deck)。B(写真集)・C(執事)は不採用
- シック化: 黄ばみ指摘により **元のフォント・カラーに復帰済み**。残すのは: バー細線3px・Persona罫線化・吹き出し罫線化・余白拡大・絵文字除去・LIVEアニメ停止
- 実装範囲 (m00138): シェル全体（左レール＋コマンドバー＋ヘッダーを含む全面刷新）
- 既存要素 (m00138): 残して再配置（Equipment/Inventory/生成画像/Blocks等の機能を壊さない）
- REVIEW 改稿の経緯: 初回 BLOCK（7指摘）→ 改稿2提出 → 再判定 BLOCK（6指摘）→ 改稿3提出 → 3度目 BLOCK（overflow 二重宣言）→ 改稿4提出 → 4度目 BLOCK（3指摘: style 除去契約未記載／cmdbar 被覆補正未記載／レール padding はみ出し）→ 改稿5提出 → 5度目 BLOCK（1語: 存在しない色トークン `--purple`。実在は `--accent-purple`。TEST ⑫ 強化も同時に要求）→ 改稿6 で REVIEW PASS・着手。**実装後 REVIEW**: 第1次 BLOCK（7指摘）→ 第2次 BLOCK（5指摘）→ 第3次 BLOCK（3点+NIT）→ 第4次 BLOCK（誤帰属2件、いずれも本計画書 md のみでコード無変更）→ 本改稿7で対応。#114 差分は 33ef562c としてコミット済み、#115/#124/#125 も並行コミット済み。着手時点で working tree は本計画書のみ untracked、**git status clean が受入条件**

## 現状把握 (EXPLORE) — 改稿で確定した事実
- `nous/api/http/dashboard.py` — tabs 9個のSSOT。`render_nav` / `render_layout_shell` は `sections/base.py`。`render_overview_tab()` はスケルトンのみ、実体はJS描画
- Overview実体: `static/features/overview/overview-core.js`（320行、`loadOverview` が `/api/dashboard/{persona}` を叩き `#overview-content` に描画）。CRUDは `overview-blocks.js` / `overview-inventory.js`
- Overview CSS: `static/styles/chat.css:2206-2390`（ov-hero/emotion/body/quick/stats）と `components.css:751,1116-1194`（ov-equip 系ほか）
- base.js の SSR ID 依存（**ガード無し**、無ければ init() が TypeError で途中死）: `#persona-select`(:226 onchange)、`#dark-toggle`(:260 onclick)、`#mem-modal-overlay`(:262 addEventListener)。ほか `#sse-status`（core/sse.js `_setSseStatus`）、`#create-persona-btn` / `#delete-persona-btn`
- `buildHamburgerMenu`（base.js:303-305）は `.header-controls` が無いと早期 return。`layout.css:259-262` は `@media (max-width:767px){ .tab-bar{display:none} }` — **どちらも `.tab-bar` / `.header-controls` のクラス名・ID に依存**
- `reset.css:40-48`: `body{display:flex;flex-direction:column;height:100dvh;overflow:hidden}`。スクロール所有者は `.main-content`（layout.css: overflow-y:auto）
- KPI 原料（**新規API不要**・改稿指摘4）: `GET /api/wiki/{persona}`（routers/memory/wiki.py:97）の `pages[]` → Wiki数＝`pages.length`、Projects数＝`pages[].project` の distinct（空除外）。`/api/project/…` 側（chat/project_context.py:89）は slug 必須・一覧なしなので不使用
- 既存 stats: `total_count`（Memories）・`linked_ratio`（persona_dashboard.py:153-157）→ 4つ目のKPIは捏造せず linked_ratio を「Linked」ラベルで表示
- モック: `output/dashboard-a-hifi.html`（282行、フォント・カラー復帰済み）

## 方針（BLOCK 指摘への回答）

### 構造 — `.tab-bar` クラス名は維持、wrapper 追加で横積み（指摘1/2/3）
- **レールは `.tab-bar` クラス名を維持**する。`buildHamburgerMenu`（`.header-controls`）と layout.css のモバイル `display:none` をそのまま生かす。`.tab-rail` への改名はしない
- SSR 構造変更は最小1箇所: `render_layout_shell` で `<nav class="tab-bar">` と `<main class="main-content">` を `<div class="app-body">` で包む。**ヘッダーは温存**（`#sse-status` / `#persona-select` / `#create-persona-btn` / `#delete-persona-btn` / `#dark-toggle` を `div.header-controls` 配下に各1つ残す。base.js:226/240/262 の null ガード無し代入が全部生きる）
- デスクトップ（`@media (min-width:768px)`）: `.app-body{display:flex;flex-direction:row;flex:1;min-height:0}`、`.tab-bar{flex-direction:column;width:76px;align-self:stretch;min-height:0;align-items:center;padding:8px 0;border-right:0.5px solid var(--separator-non-opaque)}`、`.tab-btn{width:44px;padding:10px 0;min-height:44px}` — **レール内の padding/ボタン幅は md 側で明示**（既定では `.tab-bar` 水平 padding 48px − width 76px で内容幅28pxしかなく、`.tab-btn` 水平 padding 44px がはみ出すため）。
高さ指定はしない（`.app-header` は `flex-wrap:wrap`（layout.css:11）で 768〜1024px では 2行に折り返し 60px を超えるため、`calc(100dvh - 60px)` 固定は viewport 超過→`body{overflow:hidden}` で下位タブ到達不能になる。stretch に任せる）
- **overflow は md パートの `.tab-bar` に一切置かない**（二重宣言事故 #114 型を根絶する）。既存 `layout.css:57` の `contain: layout style paint` と `:50` の `overflow-x:auto` への上書きは **`contain: layout style; overflow-x: visible` の1ルールのみ**で行う（overflow-y は既定 visible のまま触らない）
- **tip はネイティブ title に任せる**: `base.js:578-585` の DOMContentLoaded ループ（ラベルを `aria-label` に写している箇所）に `btn.title = btn.textContent.trim()` を1行追加する。CSS の `::after content: attr(aria-label)` は撤回 — クリップの影響を受けず、`font-size` 戻しも不要。`.tab-btn{font-size:0}` によるラベル視覚隠しは維持
- 低い viewport 対策: `@media (max-height:640px)` で `.tab-btn{min-height}` 縮小のコンパクト規則を1つ置き、9タブが常に収まることを確認（レールは縦スクロールに頼らない）
- モバイル（`max-width:767px`）: `.app-body{display:contents}` — 既存縦積みがそのまま継続（tab-bar は display:none、ハンバーガー導線不変）
- `body` の flex 上書きは不要になる（横積みは `.app-body` 内で完結、reset.css 無変更）。置き場所は sections.css 末尾の md パート（unlayered・link順最後で確実に勝つ）
- `render_nav` の**属性書式は 1 文字も変えない**: `test_wiki_router.py:201-232` が `class="tab-btn[^"]*"` の先頭一致と `data-loader-args="[true]"` の文字列一致を要求するため。ラベルは既存のまま（モックのtip展開は CSS hover で実現）

### クラス契約 — 改名対象外リスト（指摘5）
- **改名しない（開閉が classList 依存・delegation 契約）**: `.ov-modal-overlay` / `.ov-modal` / `.ov-field` / `.ov-modal-actions` / `.ov-modal-title` / `.ov-field-block` / `.ov-form-label` / `.ov-block-title` / `.ov-equip-*` / `.ov-inv-*` / `.ov-hl-*` / `.ov-section-title` / `.ov-quick-row` / `.ov-quick-label` / `.ov-quick-value`
- **改名しない（ID 契約）**: `#add-item-modal` / `#edit-item-modal` / `#block-edit-modal` / `#media-viewer-overlay` / `#mem-modal-overlay` / `#overview-content` / `#overview-portrait` / `#hero-portrait-slot` / `#block-modal-*`（base.py のモーダル群すべて）
- **md-* で新規追加するのは見た目の枠だけ**: crumbs / persona帯 / KPI行 / Activity・Capacity 2col / Chatプレビュー / Today's Reading。細線バー3px・罫線区切り・余白。※**Chatプレビュー本文は後送り**: `/api/dashboard/{persona}` の `context` には `last_conversation_time`（時刻のみ）しかなく dashboard レスポンスから本文は取れないため、CHARA CHAT ペインは「Chat タブへ」導線のみとする。本文は既存 `GET /api/chat/{persona}/sessions/main?limit=2`（`routers/chat/__init__.py:46` で GET 登録。`chat_messages.py:163` の `get_chat_session` は `chat_stream.py:33` の `_do_get_chat_session` に委譲し、`SessionManager.get_messages(db, persona, session_id)` が本文を返す。session_id は `getChatSessionId()`（`static/chat/history/session.js:100-103`）が常に `"main"`）で取得できるため**API 拡張は不要**。`TreeSessionWindow.from_db` は `chat_messages.py:73`（update）/:114（rollback）のみで GET 経路では使わない — 別カードで fetch 1本を足すだけ。`.md-avatar` は persona帯 イニシャル代替で今回実装
- **クラス名対応表**（モック短縮名 → 実装名スロット名。モックの構造を参照するが名前はこの表で確定）: rail→`.tab-bar`（既存維持）/ logo→`.tab-bar-logo` / cmdbar→`.md-cmdbar` / crumbs→`.md-crumbs` / persona→`.md-persona` / persona-id→`.md-persona-id` / rel→`.md-rel` / ploc→`.md-ploc` / minis→`.md-minis` / kpis→`.md-kpis` / kpi→`.md-kpi` / n→`.md-kpi-value` / l→`.md-kpi-label` / grid2→`.md-grid2` / pane→`.md-pane` / ev→`.md-event` / tag→`.md-tag` / bar-row→`.md-bar-row` / bl→`.md-bar-label` / bar→`.md-bar` / bar i→`.md-bar-fill`（data-fill/data-color） / chat→`.md-chat-pane`（Chat 導線のみ。プレビュー本文 md-msg/md-bubble/md-msg-who/md-avatar-u/md-recall-chip は未実装） / avatar→`.md-avatar`（av-h→`.md-avatar-h`） / live→`#sse-status`（既存温存） / hctl→`.header-controls`（既存温存） / hbtn→`#dark-toggle`（既存温存）。theme-note は実装不要（モック説明注記）
- **CSS 変数対応表**（モックは実在しない変数を使ってるため必須）: `--panel`→`--glass-bg` / `--cmd-bg`→`--glass-bg`（backdrop-filter 併用） / `--border`→`--glass-border` / `--border-soft`→`--separator-non-opaque` / `--text`→`--text-primary` / `--sub`→`--text-secondary` / `--faint`→`--text-secondary` / `--accent`→`--accent-blue` / `--purple`→`--accent-purple` / `--green`→`--accent-green` / `--yellow`→`--accent-yellow` / `--mono`→変数無し、`font-family: ui-monospace, "SF Mono", monospace` 直接記述 / radius は `--radius-sm`/`--radius-md`。`--text-tertiary` は実在しないので禁止
- **md テンプレートに `style=` を書かない**: `safeSetHTML` の `FORBID_ATTR`（core/dom.js:56）が style を除去し、モックの `style="width:82%…"` のまま組むとバーが全て0幅になる。バーは `<div class="md-bar"><div class="md-bar-fill" data-fill="72" data-color="var(--accent-purple)"></div></div>` とし、`safeSetHTML(el, html)` の直後に `N.Components.memoryCard.applyDataStyles(el)` を呼ぶ（`overview-core.js:326-328` の既存不変条件を継承。`applyDataStyles` は `[data-fill]` を汎用走査するので md-* 新規クラスにもそのまま効く）。**色トークンは `variables.css` の実在名のみ**（`--accent-purple` / `--accent-blue` 等。`--purple` は実在せず、構文有効で受理→計算値時 transparent になるため使用禁止）
- **chat.css:2206-2390 の処置**: 組替で JS から参照されなくなる規則のみ削除。削除候補は「JS から参照ゼロ」の `.ov-hero` `.ov-status-panel` `.ov-quick` `.ov-emotion-*` `.ov-body-*` `.ov-stats-grid` `.ov-stat-card` のみ（**`.ov-hero-portrait` は除外** — overview-core.js:37 が出力し続け、components.css:751 の `.ov-hero-portrait img` を使い続けるため温存矛盾を解消）。削除前に各セレクタを JS 全 grep して参照ゼロを確認する。`.ov-quick-row/-label/-value` は温存側
- components.css の `.ov-equip-*`（1116-1194）・`.ov-hero-portrait img`（751）は使い続けるので無変更

### KPI — 新規 API なしに確定（指摘4）
- overview-core.js で `/api/dashboard/{persona}` と並行して `GET /api/wiki/{persona}` を 1 本 fetch
- KPI×4: Memories＝`stats.total_count`、Wiki＝`pages.length`、Projects＝`pages[].project` distinct（空除外）、Linked＝`stats.linked_ratio`（%表示、無ければ `--`）
- **persona_dashboard.py は変更しない**（item5 は当初より削除）
- wiki fetch 失敗は KPI を `--` にして続行（Overview 全体は落とさない）

### ⌘K — MissionDeck モジュールは作らない（指摘6）
- `Nous.Features.MissionDeck` への言及を撤回。**⌘K は base.js 内で完結**: `(meta|ctrl)+k` keydown → コマンドバー入力へ focus → Enter で Chat タブへ遷移（`N.Core.switchTab("chat")`）
- コマンドバーの DOM は `render_layout_shell` 末尾に追加（`<div class="md-cmdbar">`、input + kbd 表示のみ）。新規 JS ファイルなし、`render_head` への script 追加なし
- **`.md-cmdbar` は Chat タブでは非表示**: cmdbar はモック同様 `position:fixed; bottom:18px` で、Chat の `#tab-chat.active{display:flex;flex-direction:column;height:100%}`（chat.css:2-8）最下部の `#chat-input-area` を覆うため。`body:has(#tab-chat.active) .md-cmdbar{display:none}` で解決（JS 追加不要）。`@media (max-width:767px)` でも非表示（モバイルはハンバーガー主導）。**`body:has()` は Safari 15.4+ / Chrome 105+ 前提** — プロジェクトは既に `100dvh`・`backdrop-filter` を使っておりサポート水準は一致。非対応環境では cmdbar が Chat 入力を覆う唯一の破綻経路として許容する
- **Chat 以外のタブでは被覆分を補正**: cmdbar（実高羞44px）＋18px の帯が最下部を恒常被覆するため、md パートに `@media (min-width:768px){ .main-content{padding-bottom: calc(24px + 56px)} }` を追加。Chat タブは cmdbar 非表示かつ全高レイアウトなので `body:has(#tab-chat.active) .main-content{padding-bottom:24px}` で戻し、モバイル（767px以下）は cmdbar 非表示のため既定 padding のまま。cmdbar は `render_layout_shell` 末尾（body 直下）に置く — `.tab-panel` の `contain: paint`（layout.css:106）の影響を受けず、fixed の基準も崩れない（パネル内へ移すとスクロールで流れる）

## 変更ファイル（確定）
1. `nous/api/http/sections/base.py` — `render_layout_shell` に `.app-body` wrapper と `.md-cmdbar` を追加。`render_nav` は無変更。ヘッダー5 ID と `.header-controls` は温存
2. `nous/api/http/static/base.js` — DOMContentLoaded ループ（:578-585、`btn.title` 追加行は :583）に `btn.title = btn.textContent.trim()` を1行追加。⌘K keydown ハンドラ（cmdbar focus → Enter で Chat 遷移）
3. `nous/api/http/sections/overview.py` — **プレースホルダのまま変更は最小**。`#overview-content` と `#overview-portrait` は `#tab-overview` の**直接子を維持**（`skeleton.js:56-58` の `:scope > [id$="-content"]` 契約。包むと `panelContentEl` が null → パネル根ごとスケルトン置換 → #91 型の永久スケルトンになる）。md 構成の骨組み（crumbs → persona帯 → KPI×4 → Activity/Capacity 2col → Chat列＋Today's Reading 2col → 既存セクション群）は **overview-core.js が `#overview-content` 内に描画**する（タブ切替のたび `show()` が中身を差し替えるため、静的クロームを外に置くと二重表示になる）。`<section id="tab-overview" class="tab-panel active" role="tabpanel">` の id → class 隣接順は維持（`test_wiki_router.py:223` が隣接一致を要求）
4. `nous/api/http/static/styles/sections.css`（末尾追記のみ）— md パート: `.app-body` 横積み／`.tab-bar` レール化（`min-width:768px`、overflow 宣言なし）／`contain` 1ルール上書き／`max-height:640px` コンパクト規則／`.md-cmdbar`（Chat・モバイル非表示含む）／細線バー、罫線帯、KPIタイポ、2col、`max-width:767px` フォールバック（`.app-body{display:contents}`）
5. `nous/api/http/static/features/overview/overview-core.js` — 描画テンプレートを md 構成へ組替（データ取得・CRUD・delegation 契約・モーダル ID/クラスは不変）。wiki fetch 追加。バー描画は `data-fill`/`data-color` 属性で出し `safeSetHTML` 直後に `N.Components.memoryCard.applyDataStyles(el)` を呼ぶ（`style=` 直接書き込み禁止）
6. `nous/api/http/static/styles/chat.css` — 参照ゼロになった ov 規則の削除（2206-2390 のうち hero/emotion/body/quick/stats 系。grep 確認後）
7. `nous/api/http/routers/persona/persona_dashboard.py` — **変更しない**

## TEST（実ブラウザ項目拡充 — 指摘リスク対応）
- pytest: `tests/integration/test_dashboard_e2e.py` `test_http_api.py` `test_http_routers.py` + `tests/unit/test_wiki_router.py`（tab-btn 属性書式の文字列一致を含む）。**drive-by**: `test_dashboard_e2e.py:211` の tailwind assert は #100 で CDN 撤去後に恒常 failing になっていたため `/static/styles/` リンク確認に置換し green に戻す（waiver なし・テスト失敗 0 を維持）
- vitest（static）: 38 files 緑維持
- **実ブラウザ（8793 or 実ポート）で以下を目視・操作**: ①テーマ切替（ライト⇄ダークで md 部分も切替）②ペルソナ切替 ③タブ切替後に `aria-selected="true"` が DOM 内に 1 件のみ ④767px 幅でハンバーガー表示・開閉 ⑤⌘K フォーカス→Enter で Chat 遷移 ⑥Equipment/Inventory/Blocks の CRUD 導線 1 本以上 ⑦Overview 実データ表示 ⑧**767/768/800/1024px の4幅でレール最下段タブ（settings/timeline/graph）を実際にクリック**（768px はレール＋ハンバーガー同時表示の既存境界。800px はヘッダー2行折返し幅） ⑨**Chat タブでメッセージ送信**（cmdbar 覆いの回帰検出） ⑩**Chat タブで cmdbar 非表示・他タブで表示**を確認 ⑪**レールのアイコン hover でラベル tip（native title）が出る**ことを確認 ⑫**`#overview-content` 内の全 `[data-fill]` 要素（気分1 `overview-core.js:197`＋ミニバー4 `:136` `MINIS`＋Capacity 最大3 `:166`/`:169`/`:173`＝最大8本。`BODY_BAR_COLORS` の `pain` は描画しない。全データが揃ったペルソナで `querySelectorAll('[data-fill]').length === 8` を等号確認 — 実測は r126 fixture（memories 2件・context_state 9キー・wiki 2ページ）で全8本出現）が `offsetWidth > 0` かつ着色されている** — 着色の判定は `getComputedStyle(fill).backgroundImage !== 'none'` または `getComputedStyle(fill).backgroundColor !== 'rgba(0, 0, 0, 0)'` の**少なくとも一方が成立**（`applyDataStyles` は `el.style.background = color` で設定するため、gradient 色は backgroundImage に、単色は backgroundColor に入る。backgroundColor のみ見ると gradient 5本を透明と誤判定する）。（0幅・色トークン不実在で transparent になる両回帰の検出。先頭1件だけ見て残りを見落とさない） ⑬**長い一覧タブ（inventory/wiki/memories）で最下部までスクロールし、最終行が cmdbar に隠れない**（padding-bottom 補正の検出）。CDP スクショ取得
- ブレースバランス・テンプレートリテラル整合

## REVIEW → GATE → COMMIT → RECORD → PUSH
- 本改稿をルアン・メェイに再提出。PASS（完全）以外は BLOCK・着手しない
- GATE: 型pass / テスト失敗0 / カバレッジ≥60% / lint 0 / format ok / 契約pass / シークレット0 / 監査≤moderate / ドキュメント同期 / 禁止操作なし
- COMMIT はオーケストレーターが1回で締める。RECORD は `project:nous` タグ
