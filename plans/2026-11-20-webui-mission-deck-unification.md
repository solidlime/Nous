# WebUI Mission Deck 語彙の全面統一 + モバイル整備 (#127)

date: 2026-11-20
kanban: #127
prev: plans/2026-11-20-dashboard-mission-deck.md (#126, commit 46125f34)

## 1. 概要

#126 で導入した Mission Deck 語彙（縦レール・md-crumbs/md-persona/md-kpis/md-grid2・細線バー・mono 数字・glass 変数）を、Overview 帯以外の全 UI に展開する。

対象:
1. Overview 内の既存セクション（Profile/Equipment/HL/Inventory/Generated Images + モーダル群）
2. 他8タブ（memories/wiki/projects/chat/activity/settings/timeline/graph）の見た目
3. 共有部品（glass-btn/glass-input/badge/card-title/toast/モーダル/skeleton/settings-form）
4. モバイル（<=767px）: 全タブ単列・ハンバーガー・モーダル/トースト全幅・チャット入力追従
5. 通知（toast）の見た目統一
6. チャット動作の仕上げ: 境界キメラ解消・入力欄/表の溢れ解消・追従担保（JS ロジック無変更）

機能・契約（クラス名/ID/属性書式/data-action delegation/API）は一切変更しない。見た目（CSS）と、CSS が依存する境界値・剥がれ bug 修正のみ。

## 2. 語彙 SSOT（これ以外の語彙を新規発明しない）

variables.css の既存トークン + #126 で導入した sections.css:511-668 の md 参照実装のみ使う。

**md レシピ**（既存部品への適用変換表）:
| 部位 | 規則 |
|---|---|
| ラベル・見出し | 0.72rem/600/uppercase/letter-spacing:0.05em/color:var(--text-muted)（.card-title が既にこの形。これを基準に波及） |
| 数字 | ui-monospace,monospace + font-variant-numeric:tabular-nums（md-kpi-value と同じ） |
| バー | 高さ3px / track var(--separator-non-opaque)（REVIEW 指摘 #1 で .md-bar と同一語彙に確定。--glass-bg-faint は light で不可視のため不採用） / fill は色変数 or linear-gradient（.md-bar 系と同じ） |
| 区切り | var(--separator-non-opaque) の 1px 罫線（影・二重線にしない） |
| パネル | background:var(--glass-bg); border:1px solid var(--glass-border); border-radius:var(--radius-md)（12px）。白背景の面は使わない |
| hover | var(--glass-bg-subtle)（色は変えない） |
| アクティブ表示 | 文字色 var(--accent-blue)（背景塗りはしない。#126 のレール選択態と同じ） |
| 影 | var(--shadow-sm) まで。浮揚演出に shadow-lg を使わない |

**veil 系（--veil-*）は残置する。** glass 系との統廃合は行わない（使用箇所が広大で利益が小さい）。新規に書く規則は glass 系変数のみ。

## 3. アーキテクチャ判断

### 3.1 カスケード（最重要）
読み込み順（sections/base.py:36-46）: variables -> reset -> layout -> theme -> components -> chat -> chat-mobile -> utilities -> sections。
**sections.css が常に最後** = 同特異度なら sections が勝つ。よって:
- 共有部品の md 化は components.css/theme.css の「既存規則を直接書き換える」形で行う（chat.css が共有部品クラスを再定義していないことを EXPLORE が grep 実証済み。例外は .ov-hero-portrait のみ -> 3.4 で解消）
- sections.css には「タブ別規則の md 化」と「md 語彙の追加定義」だけを書く

### 3.2 ブレークポイント単一化
シェル境界を **768px に単一化**: >=768 デスクトップ（レール） / <=767 モバイル（ハンバーガー・単列）。
- layout.css:185 の max-width:768px hamburger -> 767px
- layout.css:265-277 の中間帯 `@media (min-width:769px) and (max-width:1024px)` -> **min-width:768px に変更**（:274 の .main-content padding:20px は 5.1 のとおり削除して 16px に統一）
- chat.css:2108 の `@media (max-width:768px)`（.chat-help-tooltip 系）-> 767px
- chat.css:520 の min-width:769px（desktop collapsed）-> 768px
- chat-mobile.css 全 max-width:768px -> 767px / min-width:769px -> 768px
- chat-core.js:141,310,332,506 の window.innerWidth <= 768 -> **<= 767（4箇所。JS 変更はこの境界値のみ）**
- 900px 境界（md-kpis 折返し・memory-panel 幅）は「コンテンツ折返し」として残す
- 640px 境界も残す（現状維持）
- これにより 768px ちょうどでの「レール有り＋チャットがモバイル扱い」「ハンバーガーとレール同時表示」の両キメラが解消する

### 3.3 z-index のトークン化
直書き 3系統（1000/1100/--z-modal=400）を解消:
- .ov-modal-overlay の z-index:1000 -> var(--z-modal)
- .mem-edit-overlay の z-index:1100 -> calc(var(--z-modal) + 100)（mem 編集が ov モーダルより上という現状の相対順を維持）
- #media-viewer-overlay・#create-persona-modal（.persona-modal）も同一トークン系へ
- 結果として toast(--z-toast=500) が全モーダルより上になる（現状 1000 のモーダルが toast を覆う不具合の是正）
- .md-cmdbar は既に var(--z-sticky) のため触らない

### 3.4 chat.css 内の Overview 専用 CSS の移設
chat.css:2206-2280 の .ov-hero-portrait/.ov-quick-2/.ov-quick-*/.ov-section-title 系は Overview 専用。**sections.css の md 末尾に同名規則を追記し、chat.css 側該当ブロックを削除する**（#126 で chat.css から旧 ov-* を一掃したのと同じ手法。読み込み順で sections.css が勝つため、追記が先に効き、削除で二重定義が消える）。
**.character-flag（chat.css:2270）はチャット部品**（chat-core.js:591 がメッセージに付与するバッジ）なので **chat.css 残置**。移設対象外。なお .character-flag-img/-name/-desc は実在しない（grep 0件）——移設リストにも書かない。
chat.css:2251 の `@media (max-width:768px)` ブロック内の .ov-* 規則は移設（境界 767px に合わせる）、**.chat-msg 補正（max-width:95）は 5.3 の一本化に従い .chat-msg 側だけ残し .chat-bubble{max-width:95%}（:2261）は削除する**。**同 @media 内の `.chat-tool-call summary,.chat-tool-result summary{padding:5px 8px}`（:2264-2267）は残置する**（≤767 でツール要約の余白が消えるのを防ぐ。削除範囲に入れない）

### 3.5 対象外
- features/resonance.*（孤児ページ: 参照元なし）— 触らない。別カード候補として記録のみ
- --veil-* -> --glass-* 置換 — 行わない
- chat の送信/ストリーム/abort の JS ロジック — 無変更（境界値4箇所のみ）
- toast.js — 無変更（.toast/.toast-{type}/.toast-action-btn/toastOut keyframes 契約のまま CSS 側のみ md 化）
- features/graph.js（68.5K）の JS — 無変更

## 4. 担当分割（ファイル分離厳守・1ファイル1人形）

| 担当 | ファイル | 人形 |
|---|---|---|
| 共有部品 | components.css / theme.css / layout.css / reset.css / utilities.css | #011-A |
| タブ別+シェル | sections.css / sections/*.py / features/projects.js / features/settings/settings-core.js | #011-B |
| chat | chat.css / chat-mobile.css / sections/chat/*.py / static/chat/chat-core.js | #011-C |

sections.css は人形B単独。chat.css は人形C単独。ov-* 移設は「B が sections.css に追記」+「C が chat.css から削除」の分業（同一コミットで最終状態が正しくなる。中間状態は誰も検証しない）。

## 5. 変更詳細

**行番号は記述時点の目安**。編集時に行番号がずれていたら、セレクタ・クラス名の一致で実ファイルの該当規則を探して作業すること（行番号アンカーで隣接規則を消さない）。

### 5.1 人形A: 共有部品（components/theme/layout/reset/utilities）

**theme.css**:
- .glass-btn（theme.css:53）: md 化 — 背景を var(--glass-bg-faint)、border 1px var(--glass-border)、radius var(--radius-sm)、hover は var(--glass-bg-subtle)、shadow は付与しない
- .glass-input（theme.css:36）: **現行維持**（背景 `var(--glass-bg-subtle)`、border `0.5px solid var(--glass-border)`、radius var(--radius-sm)、focus は border-color accent-blue + ring、html.light 上書き:46 も温存）。変更しない。**入力欄 3 系統（.ov-field / .chat-field-input）をこの glass-input の値に合わせる**（glass-input 側は無変更）
- scrollbar（theme.css:148-160）: 一本化のため残置

**components.css**:
- .toast（:359）: md 化 — var(--glass-bg) + blur 既存維持、radius var(--radius-md)、border var(--glass-border)。toastOut keyframes と .toast-{success,error,info,warning} の left-accent 色は温存
- .toast-action-btn（:375）: rgba(255,255,255,.15) -> var(--glass-border)（ライト対応）
- モーダル3系（.mem-modal-overlay:395 / .confirm-overlay:457 / .shortcut-help-overlay:488）: z-index -> var(--z-modal)、radius var(--radius-lg) 統一、overlay 背景は温存
- .ov-modal-overlay（:981）: z-index 1000 -> var(--z-modal)。**var(--bg-secondary) 宣言は温存**（chat-wiring-feed.test.js:256-267 が components.css を直読みする契約）
- .ov-field（:1075）: 見た目を **glass-input の現行値と同一化**（背景 `var(--glass-bg-subtle)`、border `0.5px solid var(--glass-border)`、radius `var(--radius-sm)`、focus 同欄）。**rgba(255,255,255,...) 直書き禁止**（同テスト契約）
- .mem-bar-track（旧:1238）/ .modal-progress-bar（旧:1297）/ .wiring-track（旧:1371）: rgba(255,255,255,.1) -> var(--separator-non-opaque)（REVIEW 後の記録。元案の --glass-bg-faint は light で不可視のため実装時に差し替え。wiring-track の既存 light 上書きは削除して統一）
- .mem-tag-chip（:1249）: components 側定義を削除 — sections.css:208 が勝っており死んでいる（二重定義解消）
- .modal-progress*（:1289-1306）: sections.css:382-384 が勝っているため、components 側の二重定義を削除し sections 側に一本化（mem-modal.js:74-89 の見た目は flex:1/8px 側が現行実効値なので維持）
- .table-card-mobile（:570-609）: 削除（参照0件の休眠部品。!important 2件も消える）
- .stat-value（:13）: layout.css:192/284 のモバイル 1.5rem 固定が clamp を潰す問題 — layout.css 側を削除して clamp を通す
- .settings-search-card（:759）: sticky top:120px -> top:calc(var(--header-height) + 16px)
- .global-apply-section の二重定義（:212 と :333）: :212 を削除し :333 に一本化
- .card-title 系: 現行 uppercase 語彙は md と同一なので色味のみ微調整（--text-muted 確認）
- .badge 系: 現行維持（rgba(accent,.15) 語彙は md と同一）

**layout.css**:
- :185 の max-width:768px -> 767px
- .section-panel（:308-311）: 削除（参照0件）
- layout.css:184 の `@media (max-width:768px)` 帯にある `.main-content { padding:16px }`（:190）は、この帯を 767px 化すると 768px ちょうどで不適用になり base :99 の 24px に戻ってしまう。**この 1 行を帯から外し、新設の `@media (max-width:1024px) { .main-content { padding:16px } }` に置く**（≤1024px は 16px、>1024px は 24px で一本化。768px と 1024px が同値になり TEST ⑩ の「1024px と同等」が成立する）。**既存の `@media (min-width:769px) and (max-width:1024px){.main-content{padding:20px}}`（:274-276）は削除する**（769-1024px が 20px のまま残ると記述順勝負で新ブロックに干渉する。769-1024px も 16px に統一）。新ブロックの挿入位置は **:277 直後**（帯の削除跡の直後。3.2 の中間帯 768px 化とセットで 769-1024 を 16px 一本化する）
- layout.css の見出し規則は **h2 系を全廃して .tab-head に一本化**: `.tab-panel > div:first-child`（:121-125）、`.tab-panel h2`（:126-131）、`.tab-panel h2 span`（:136）を削除する（h3/h4 の規則 :132-135, :137-138 は他タブで使用のため**残す**）。`.tab-head` は sections.css 側に「現行 inline 実効値をそのまま写す」: `margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--glass-border); display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px（外側 div の flex+space-between は4タブのボタン群右寄・単一子タブは左寄せのまま）`、h2 は font-size:1.25rem/font-weight:700/display:flex/align-items:center/gap:10px（gap は現行 inline の実効値）、`.tab-head h2 span` は font-size:1.4rem アイコン用」を定義。Chat 見出し（chat_layout.py:41）も 5.3 で .tab-head 化するため、全タブが同一規則になる
- :192/284 の .stat-value 上書き: 削除（前述）

**reset.css**: scrollbar 規則（:56-68）のみ削除（theme.css:148-160 に一本化）。他触らない。

**utilities.css**: 変更なし（#100 の Tailwind 互換層。.lg:grid-cols-2 は 1024px で 2col、未満 1col が現行実効でありモバイル単列は既に担保）。

### 5.2 人形B: タブ別+シェル（sections.css / sections/*.py / projects.js / settings-core.js）

**sections/*.py 全8タブの見出し共通化**:
- sections/{overview,memories,activity,knowledge_graph,projects,settings,timeline,wiki}.py の `<div style="margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--glass-border);">` + `<h2 style="...">` インライン見出し帯（例: memories.py:8-10, overview.py:9, wiki.py:15）を `<div class="tab-head"><h2>...</h2>...</div>` に置換して **.tab-head に一本化**。**h2 のテキスト・DOM の ID・data-* 属性は不変**。chat の見出し（chat_layout.py:41）も同じく .tab-head 化するが実装は人形C担当（5.3）
- **timeline.py:34 の2つ目の h2（font-size:1.1rem、`<i data-lucide>` アイコン付き）は `.tab-panel h2` の display:flex を継承に依存しているため、削除後は整列が崩れる。`class="tl-subhead"` を付与し、sections.css に `display:flex; align-items:center; gap:10px; font-size:1.1rem` を定義**（.tab-head の外・別規則として）
- sections.css に .�tab-head を定義（5.1 側の定義と同一）: `margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--glass-border); display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px` + `.tab-head h2` は `font-size:1.25rem; font-weight:700; display:flex; align-items:center; gap:10px` + `.tab-head h2 span` は `font-size:1.4rem`（アイコン用のみ。補足テキスト span は実在しない） + **`.tab-head img` は `width:40px; height:40px; border-radius:50%; object-fit:cover; flex-shrink:0`**（chat の avatar。5.3 chat_layout.py の inline 全廃で失われる5点を写す）
- **test_wiki_router.py の文字列契約（:214-231）に触れる属性は出力順も含めて 1 文字も変えない**

**sections.css タブ別既存規則（8-510行）の md 化**（クラス名・構造不変、プロパティのみ）:
- activity（8-151）: .act-toolbar を md-cmdbar 相当の glass 帯に、.act-session-header は罫線区切り、.act-event の左ボーダー縦線は温存しつつ太さ 1px、.act-tool-table は mono 数字（時間・duration）+ 罫線行
- graph（152-204）: .graph-limit-btn.active を「背景塗り -> 文字 var(--accent-blue) + 上下罫線」の md 選択態に、.graph-spinner 温存、vis-tooltip 系 !important は温存
- memories（205-403）: .adv-search-panel を md-pane 相当（glass-bg + radius-md）、.mode-btn/.view-btn を glass-btn 相当、.mem-toolbar は tab-head 直下の1本帯、.memory-card は glass-bg + 罫線 hover glass-hover、.mem-batch-bar は glass 固定帯、.form-* 系は glass-input 同見た目、.mem-edit-overlay/.mem-edit-modal は z-index -> calc(var(--z-modal) + 100)・radius-lg
- settings（404-415）: .setting-category-card を md-pane 相当
- timeline（416-471）: .tl-toolbar を glass 帯に、#tl-legend の凡例 dot 温存
- wiki（472-510）: .wiki-item を md-event 相当（罫線行・hover subtle・active 文字色）、.wiki-chip/.wiki-rev mono 数字、#wiki-article-body の本文タイポ温存
- md 末尾（511-668）: #126 参照実装。**.ov-quick-*/.ov-hero-portrait/.ov-section-title の md 新規則を追記**（.character-flag は chat 部品のため対象外）（chat.css からの移設受け入れ。#hero-portrait-slot 既存規則 :626 は維持）
- @media (max-width:767px): memories ツールバー縦積み（:298 既存）維持、activity/memories/settings の1col 化は既存 utilities で担保

**sections/*.py 個別**:
- timeline.py:38 の #tl-tag/#tl-min-importance: glass-input クラスを付与（現状クラス無し・id 依存の CSS :422-435 をクラス経由に）
- memories.py:20 の `<option>` 内 `<i data-lucide>` 22件: 削除（option 内要素は描画されないノイズ）
- overview.py の .glass.p-6.mb-6 骨格: 温存（overview-core.js が全差替）

**projects タブの inline style 全剥がし**:
- sections/projects.py:11-24 と features/projects.js:21-78 の全 inline style をクラス化: .proj-form（flex 行・slug 入力）+ .proj-section/.proj-section-title/.proj-row/.proj-badge-row を新設し sections.css に md 語彙で定義（safeSetHTML の FORBID_ATTR で style が剥がれ実質素の状態になっている現状 bug の是正を兼ねる）
- data-project-wiki リンク語彙は不変

**settings-core.js:52**: 警告バナーの style="border-left:3px solid..." は safeSetHTML に剥がれて効いていない。クラス化（.settings-warn-card を新設し sections.css 側で定義）。

### 5.3 人形C: chat 系（chat.css / chat-mobile.css / sections/chat/*.py / chat-core.js）

**chat.css**（2457行・クラス名契約不変、プロパティを md 化）:
- .chat-bubble（:114）: glass-bg 化 + 罫線、max-width の二重%は .chat-msg 側 92% に一本化（:2258 の <=768 補正は境界修正後も機能するよう維持）。**860px 上限（`max-width:min(92%,860px)`）は .chat-msg 側へ移す**（広幅で行長が無限に伸びるのを防ぐ）
- .chat-tool-call（:143）/.chat-tool-result/.chat-tool-summary-left: md 化 — 罫線区切り・glass-bg、.chat-tool-status の色語彙温存
- .chat-thinking-bubble（:315）/.chat-monologue-bubble（:387）: より淡い glass-bg-faint + 罫線
- #chat-input（:49）: glass-input 同見た目 + **min-width:0 追加**（:42 の #chat-input-area 横溢れ解消）
- #chat-messages（:32）: **min-height:0 追加**（iOS flex 子の縮み欠落解消）
- .chat-bubble table（:1694 付近）: th の white-space:nowrap -> normal + .chat-bubble table に display:block; max-width:100%; overflow-x:auto（表の横溢れ解消。pre の既存 overflow は温存）
- .chat-command-popup（:2148）: max-width:calc(100vw - 24px) 追加
- #settings-panel（:511）+ details/summary アコーディオン（:580-685）: md 化 — summary は uppercase ラベル + 罫線、開閉 chevron 温存
- .chat-field-label/-input（:686-699）: glass-input の現行値と同一見た目。**:713-718 の .chat-field-input:hover/:focus 独自規則（背景 rgba(accent,.05) 等）は削除し、glass-input の :focus 挙動に統一**
- .memory-item-card（:1217 付近）: md-event 相当
- .hljs-block-wrapper（:1724）+ .chat-file-chip（:1417）: glass + 罫線
- .chat-welcome（:1097）: 温存（壊すリスク大・既に整ってる）
- .chat-preset-grid（:2444）: grid-template-columns:auto 1fr 1fr 1fr -> **auto minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)**（auto はラベル欄として温存、入力欄 3 列のみ minmax(0,1fr) 化で潰れ解消）+ **`.chat-preset-grid .chat-field-input { min-width:0 }` を 1 行追加**（入力要素の自動最小幅でトラックから溢れるのを防ぐ）
- .settings-sticky-header（:2184）: モバイル padding 12px との食い合わせを margin:0 -12px 12px に修正
- **:2206-2280 の ov-* ブロック（.ov-hero-portrait/.ov-quick-*/.ov-section-title/@media 内 .ov-*）: 削除**（人形B が sections.css に移設済みのため。.character-flag は chat 部品なので残置。@media 内は .chat-msg 補正と .chat-tool-call summary/.chat-tool-result summary padding（:2264-2267）を残置し、.chat-bubble 95%（:2261）は削除）
- light 補正（:283-312）: 変数化で不要になる規則は随時削除

**chat-mobile.css**（219行）:
- 全境界 <=768/>=769 -> **<=767/>=768**（:12,:74 ほか）
- :20 の min-height:350px -> min-height:min(350px, 50dvh)（低 viewport で入力欄押し出し解消）
- :79-82 の @media (max-width:900px){#memory-panel{display:none}} と chat-core.js の style.display="flex" 競合: **この display:none 規則を削除し、chat-core.js のパネル表示制御に統一**（769-900px での強制表示バグ解消。chat-core.js 側の初期状態制御を実装時に確認の上、CSS 依存を剥がす）
- :25 の #memory-panel[style*="display: flex"]: **残置**（JS 無変更原則優先。chat-core.js の該当 style 設定文字列は変えない）
- :171/:183 の二重 scrollbar 定義: 1件に削減
- #settings-panel のモバイル全面化（:24）: 温存・境界のみ修正
- :102-118 の !important 対抗群: chat_layout.py の inline style 削除（下記）により不要になる規則は削除。**ただし chat-mobile.css:122-127 の `#tab-chat h2{font-size:1.05rem !important}` / `#tab-chat h2 span{font-size:1.15rem !important}` は「!important のみ外して規則自体は残置**（インライン対抗であると同時にモバイルでの意図的縮小。`#tab-chat h2` は特異度 1,0,1 で .tab-head h2 に勝つため !important 無しで機能する）

**sections/chat/chat_layout.py**:
- :41 のインライン style（h2/avatar 40px 等見た目系）: **外側 div に .tab-head を付与し、インライン style を全廃**（h2 のテキスト・ID・data-* は不変。avatar img の 40px は .tab-head img として sections.css 側の .tab-head 定義に含める）。chat-mobile.css:120-137 の `!important` 対抗規則はこれにより不要になるものを削除

**chat-core.js**:
- :141,:310,:332,:506 の window.innerWidth <= 768 -> <= 767（4箇所のみ。他の JS 無変更）

### 5.4 オーケストレーターが TEST 時に直す枠
実ブラウザ検収で見つけた細部（数 px の余白・コントラスト）は私が直接修正する。範囲は「上記仕様の趣きを壊さない調整」に限る。

## 6. 不変契約（違反は即 REJECT）

1. **render_nav 属性書式**（base.py:133-169）: class="tab-btn..." 先頭・data-tab/data-loader/data-loader-args="[true]"/data-self-managed/aria-selected の順序と書式（test_wiki_router.py:214-231）
2. **id="tab-X" class="tab-panel active" 隣接順**（base.py render_layout 側）
3. **クラス名・ID 全般**: .ov-*（19種）・.md-*・.chat-*・.mem-*・.act-*・.tl-*・.wiki-*・.wiring-*・.setting-*・#hero-portrait-slot 等、本計画で「削除」「改名」を明示したもの以外は 1 つも変えない
4. **CSS 直読みテスト契約**（static/chat/chat-wiring-feed.test.js:256-267）: components.css の .ov-modal{...var(--bg-secondary)} 存在・.ov-field の rgba(255,255,255 直書き禁止・.wiring-kind-link_fire .wiring-kind-badge{...var(--accent-purple-rgb)} 存在
5. **toast.js 依存**: .toast/.toast-{type}/.toast-action-btn/toastOut keyframes/3.2s 自動削除
6. **delegation 属性**: data-action=/data-ov-action=/data-ov-tab=/data-tab=/data-block-action= 全維持
7. **JS ロジック**: 変更は chat-core.js の境界値4箇所のみ。送信/ストリーム/abort/追従（send/render.js:164-175, turn.js:87）には触らない
8. **#126 改名禁止リスト**（plans/2026-11-20-dashboard-mission-deck.md:36-39）を全部引き継ぐ

## 7. 検証計画（TEST 項目 = 機械判定）

1. pytest tests/unit/ 全件（.py 変更の回帰。pre-existing は個別識別）
2. npx vitest run 38 files 全緑（CSS 直読みテスト含む）
3. node --check 変更全 .js
4. CSS 監査: braces バランス・未知変数ゼロ（var(-- 全数点検 vs variables.css 実在）・rgba(255,255,255 直書き残存は許容リスト明示の上でレビュー
5. 境界単一性: JS に <= 768 残存ゼロ・CSS に max-width: 768px / min-width: 769px 残存ゼロ（767/768 指定に置換後）
6. z-index 直書き残存ゼロ（グローバル層＝--z-toast/--z-modal/--z-sticky 系と同格の新規層は --z-* or calc(var(--z-*)+N) のみ。keyframes 内は許容。positioned 親内の局所スタッキング（z-index:1/2/10 のような小値）は実装欠陥ではなく許容 — chat.css:722/1499, sections.css:469 の3件に加え、wiki 編集フォーム #wiki-edit-title/#wiki-edit-body の background: rgba(15,23,42,0.45) 直書き（pre-existing・light でも可読）を許容リストに明示）
7. toastOut keyframes 存在
8. SSR smoke: 各タブのパネル ID・data-loader 属性・見出し h2 テキストが変更前と同一（#126 の手法）

## 8. 実ブラウザ検収（TEST の目視フェーズ・8793）

サーバ: NOUS_DATA_ROOT=/tmp/r127-data で r126 fixtures を流用、ポート 8793。

| # | 検証 | 判定 |
|---|---|---|
| 1 | 360px 幅: 全9タブ、横向きスクロール無し・ハンバーガー動作・トースト全幅・モーダル全幅・チャット入力欄が画面内 | 9/9 タブで崩れゼロ |
| 2 | 768px ちょうど: レール表示・ハンバーガー非表示・チャットがデスクトップレイアウト（キメラ解消の直接確認） | キメラゼロ |
| 3 | 1024px: overview の md-grid2 2col・KPI 4枚・wiki 3col | 現行維持 |
| 4 | light テーマ: .mem-bar-track が可視（ライト不可視是正）・全タブで白直書き由来の白飛びゼロ | 全バー可視 |
| 5 | チャット動作: 送信->応答ラウンドトリップ・追従停止/再開・中止ボタン・入力欄フォーカス | 全稼働 |
| 6 | トースト: memories 追加等で success 表示・swipe-dismiss | 表示可 |
| 7 | CRUD 導線: memories 追加/編集・wiki 編集保存・overview 装備解除・プロジェクト slug 切替 | 全導線稼働 |
| 8 | 見出し統一: .tab-head 化した8タブで見出し帯が同一デザイン | 8/8 |
| 9 | 移設検証: .ov-quick-* が Overview で移設前と同見た目（chat.css 削除後も sections.css で描画） | 視覚リグレッション無し |
| 10 | **768px ちょうど（width:768 実測）**: main-content padding 16px（新設 ≤1024px 帯の適用で 1024px と同値）。チャット入力欄確保。settings-panel-close 非表示（≥768）。tab-bar が 76px 縦レールで表示。#tl-legend 折返り。.chat-msg が base 92%（mobile 95% 補正は非適用） | 全項目実測 OK |
| 11 | テーマ切替: dark/light 両方で全9タブに破綻無し | 両テーマ健全 |

## 9. 受け入れ条件

- pytest 全緑（pre-existing は stash 実証の上で例外扱い）
- vitest 38 files 全緑
- 実ブラウザ 3幅（360/768/1024）x 2テーマで視覚的破綻ゼロ（横スクロール・重なり・溢れ・不可視）
- 768px キメラ解消の実測
- light テーマで全バー可視
- クラス名・ID・属性書式・delegation 不変（契約テスト緑で担保 + SSR smoke）
- 死規則の削除（.section-panel/.table-card-mobile/.mem-tag-chip 二重/scrollbar 二重/.global-apply-section 二重）
- コミットは1本（feat(webui): ...）にまとめ、RECORD + PUSH まで


## 10. リスクと対応

| リスク | 対応 |
|---|---|
| sections/*.py 変更で SSR 契約を壊す | test_wiki_router の文字列一致を守る + SSR smoke を TEST に含める |
| chat.css 大規模変更でチャット操作が壊れる | JS 無変更（境界4箇所のみ）+ 実ブラウザで送信まで確認 |
| CSS 直読みテスト（chat-wiring-feed）違反 | .ov-modal/.ov-field の宣言を静的に守る（§6.4） |
| 人形並列での編集衝突 | ファイル分割厳守（§4）。sections.css は B 単独、chat.css は C 単独 |
| md 化の過剰適用で可読性低下 | §2 のレシピ範囲のみ。新語彙の発明は計画書 REVIEW で弾く |
## 11. TEST 記録（2026-11-20。tests/contracts は pact 依存のため除外）

### 自動テスト（統括環境）
- pytest: **3681 passed, 4 skipped**（新規 test_tab_head_markup.py 77行を含む）
- vitest: **38 files / 402 tests 全緑**（chat-wiring-feed の CSS 直読み契約を含む）
- CSS braces バランス: 全10ファイル OK
- 未知 CSS 変数: ゼロ（--act-color/--chip-hue は sections.css 内ローカル定義のスコープ変数のため誤検知）
- 境界排他 grep: `max-width:768px` / `min-width:769px` 残渣ゼロ。layout.css は 767 帯（:168/:241/:280）+ 中間帯 `min-width:768px and max-width:1024px`（:246）、chat-mobile.css は 767/768 に統一

### 実機検証（8793 / r127-data）
- .tab-head 9タブ SSR 出力: ✓（memories タブで head=yes、flex/罫線を実測）
- #tl-tag glass-input 適用: ✓（bg rgba(255,255,255,.08)/border 1768hover 系、radius 実測 — light 上書きも :46 で有効）
- .proj-form glass 適用: ✓
- ライトテーマ切替: ✓（#dark-toggle クリック → htmlClass=[light]、bodyBg=rgb(255,255,255)、.glass-input に theme.css:46 の light 上書き適用）
- memories 動的リストの実機完走: ×（後述のヘッドレス問題により未検証。ただし CSS クラス名不変＋402 vitest で担保）

### drive-by 記録（#127 スコープ外・要観察）
1. **wiring/stream SSE 再接続ループ**: ローカル 8793（Qdrant 無し）で GET /api/memory/wiring/stream が494回（全て200）呼ばれ続けた。core/sse.js は5秒→倍々バ2のバックオフ実装済みなのに即再接続が続いた。ユーザー実環境（Qdrant 有り）では未再現の可能性。
2. **ヘッドレスブラウザで fetch の Promise が解決しない**: サーバは /api/observations に 200 を返しているのに、ブラウザ側の .then() が発火しない（リロード直後も同様）。loadMemories が skeleton から進まない原因。browser-use/Chromium 固有か、6接接プールと SSE の干渉の可能性。実環境で memories タブの中身が空で止まる場合はこの2件を疑うこと。
