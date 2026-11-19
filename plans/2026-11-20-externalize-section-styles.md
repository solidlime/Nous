# #99 スタイル4層分散の解消 — sections 埋め込み style の外部化

## 症状と現状

スタイル定義が4層 (外部CSS / section 埋め込み `<style>` / inline style / Tailwind CDN) に分散し、
タブごとに別系統のスタイル運用・テーマ不整合の温床になっている。

層ごとの現状:

| 層 | 状態 |
|---|---|
| Tailwind CDN | **解消済み** (#100 で utilities.css 化、base.py から CDN 無し) |
| inline style (projects.py) | **解消済み** (#97 done) |
| 外部CSS | static/styles/ 8ファイル 5014行 |
| section 埋め込み style | **今回の対象**。6ファイル計~480行 |

埋め込み style の実態 (EXPLORE 済み):
- activity.py:143行 / memories.py:183行 / timeline.py:55行 / knowledge_graph.py:51行 / wiki.py:38行 / settings.py:11行
- どのファイルもテーマ変数 (--glass-border / --text-muted / --accent-*) を既に主に使用
- クラス名は act-* / mem-* / wiki-* 等タブスコープ。6 section 間の同名クラス衝突なし (.active/.open 修飾子のみ)
- 外部CSS側から既に参照あり: theme.css:116 `.copy-btn:focus-visible`、components.css:645 `.view-toggle .view-btn` (モバイル min-height) — いずれも詳細度で勝っており、外部化による順序逆転の影響なし
- フォーム部品は memories 埋め込みが自前系 (.form-label/.form-textarea/.glass-range)。外部CSSには glass-input 本体・ov-* 系・chat-field-input 系の計3系統が既に並存

## 設計判断

1. **移設先は1ファイル**: `static/styles/sections.css` (タブ別コメント区切り)。
   #93 の教訓 (定義の多箇所管理がバグの温床) から、タブ別ファイル分割はしない。
2. **カスケード順の維持**: 埋め込み style は body 内 = 全 `<link>` より後で勝っていた。
   sections.css を link 順 **utilities.css の直後** (=最後) に置き、**@layer に入れない** (unlayered)
   ことで埋め込み当時の強さを再現。variables.css の @layer 宣言は既存8ファイルと同じ扱い。
3. **クラス名は不変**: HTML 側・JS 側の変更はゼロ。<style>〜</style> の削除のみ。
4. **テーマ変数への寄せ (症状「テーマ不整合の温床」への治療)**:
   - 白ベール `rgba(255,255,255,0.0x)` **21箇所** (activity 13 / memories 6 / timeline 2、突合確定値 0.02×2 / 0.03×4 / 0.04×5 / 0.05×2 / 0.06×2 / 0.07×1 / 0.08×4 / 0.1×1) は
     ライトテーマで白背景に白を重ねて消える = 実害。variables.css に **4段の新変数**を追加:

     | トークン | dark 値 | light 値 (Apple systemFill 系 `rgba(120,120,128,α)`) | 引き受ける元の値 (実測) |
     |---|---|---|---|
     | `--veil-faint` | 0.02 | 0.08 | 0.02×2 (同値), 0.03×4 (±0.01) = 6件 |
     | `--veil-subtle` | 0.04 | 0.12 | 0.04×5 (同値), 0.05×2 (±0.01) = 7件 |
     | `--veil` | 0.06 | 0.16 | 0.06×2 (同値), 0.07×1 (±0.01) = 3件 |
     | `--veil-strong` | 0.08 | 0.20 | 0.08×4 (同値), 0.1×1 (レビュー第2回で veil-strong 化 — **唯一の知覚閾値超え**: dark Δ0.02、#2c2c2e 上の合成輝度 65.1→60.9 = 1.65%/255) = 5件 |

     合計 21 箇所全てがトークン置換 (当初 0.1 は literal 維持予定だったが、レビュー第2回指摘1で
     「ライトテーマで溝が消える = このカードの症状が1箇所残る」と指摘され var(--veil-strong) 化)。

     - 丸めは多くの箇所で **±0.01** (8bit 換算1%輝度差 = 知覚閾値以下) → dark はその範囲では知覚差ゼロ。
     - **例外 1箇所**: glass-range トラック (sections.css:343) の 0.1→0.08 は **Δ0.02**、合成輝度差 1.65% で知覚閾値 (1%) を超える — 第2回 REVIEW 指摘1の修正で意図的に許容 (light テーマで溝が消える症状を優先)。
     - light 値は Apple の fill 系に倣い `rgba(120,120,128,α)` — 白背景でも `--bg-grouped` 上でも読める。
     - 既存 `--glass-border` (dark=白0.08 / light=黒0.08) と同じ相対スケール上にあることを変数定義に1行コメント。
   - 赤系 `rgba(248,113,113,…)` (memories batch bar 2箇所) → `rgba(var(--accent-red-rgb), …)`。
     **これは視認可能な色変化** (248,113,113 → 255,69,58 で彩度上昇) — テーマ accent への統一として意図的。
     併せて `--accent-red-rgb` に **html.light 上書き `255, 59, 48` を追加** (**赤の** hex↔rgb 食い違いの解消。
     green/yellow/orange/teal/purple の rgb 側 light 上書き欠落は残存 → 別カード)。
   - モーダル暗幕 `rgba(0,0,0,0.6)`、wiki コード背景 `rgba(15,23,42,*)` は**テーマ非依存の意図的暗色**として維持
     (chat 側のコードブロックも同様。ライトテーマでコードが白背景化する方が不整合)
5. **base.py の link に不変条件コメント**: `<!-- sections.css は必ず最後・unlayered を維持（埋め込み <style> と等価な強さ。link 順・@layer 無登録を崩さない） -->`
6. **`@keyframes fadeIn` → `mem-fade-in` にリネーム** (定義・使用とも memories 内1箇所のみ確認済み。汎用名のセクションCSS内常駐は将来の衝突要因)
7. **sections.css 冒頭に規律コメント**: `Tab-specific rules ONLY. Shared components belong in components.css.` + 汎用名の注記 (`Generic-looking names (.form-*, .copy-btn, .mode-btn, .view-btn, .range-value) are memories-form-scoped: current consumers are memories only.`) — 実物 sections.css:2-4 と文面一致 (1行目はファイル名ヘッダ、5-6行目は unlayered 注記)
8. **副次的地雷の除去**: core/dom.js ALLOWED_TAGS に `style` が無いため、将来セクションを遅延ロード (safeSetHTML) にした瞬間
   埋め込み style は無言で剥がれる — 今回の外部化はその地雷の除去でもある。
9. **スコープ外 (明記)**:
   - フォーム部品の完全1系統化 (glass-input ↔ chat-field-input ↔ ov-* ↔ form-* の一本化) —
     視覚変更を伴うデザイン統一は別カード。このカードは構造 (配置) の統一のみ。
     **移設中に5系統目を作らない** (memories 由来の .form-* はそのまま移す。新規部品の定義を増やさない)
   - 既存外部CSS内の白ベール置換 — 埋め込み由来分のみ (chat.css は html.light 対応済み)
   - **components.css:614-662 の @media 767px ブロック内の等詳細度規則** (.adv-search-row gap:6px 等は
     memories 埋め込みに body 内後勝ちで**現在 dead**。移設後も dead のまま維持 = 挙動同一。
     「4層解消」後の本規則の統合/削除は別カード #114)
   - **persona_dashboard.py:288-343 の _render_setup_page 自前 `<style>`** (7箇所目の同病:
     .glass/.glass-input/.glass-btn 再定義 + #a855f7 直書きで accent 不一致。独立ドキュメントのため対象外 → 別カード #115)
   - **settings の青系 focus/reset 色 rgba(96,165,250,0.1/0.2/0.08/0.15/0.18) 計6箇所 (4行、sections.css:393-396)** (.setting-reset-btn bg 0.1 + border 0.2 / :hover bg 0.2 / .cat-reset-btn bg 0.08 + border 0.15 / :hover bg 0.18) — テーマ非依存のまま移設。移設前からの既存色で動作同一だが、「21箇所全て置換」は白ベールの話で、青系は本カードでは手をつけていない (accent は --accent-blue 系ではなく直書きだが、settings タブ単独の色なので影響は局所)。テーマ寄せは別作業。
  - projects.py 等の inline style — #97 で解消済み
   - Tailwind CDN — #100 で解消済み

## 実装ステップ

1. `variables.css`: --veil 4段追加 (+html.light 値) + html.light に --accent-red-rgb 追加
2. `sections.css` 新規: 6ファイルの style 内容を移設 (上記変数置換込み、タブ別コメント区切り)
3. `base.py`: utilities.css の直後に sections.css の link を追加
4. 6 section .py から `<style>` ブロック削除 (HTML 文字列のみの変更、Python ロジック無接触)
5. 検証:
   - `grep -c 'rgba(255,255,255' sections.css` → **0** であること (0.1 literal も第2回 REVIEW で var(--veil-strong) 化したため、白ベールは全廃)
   - 突合の主張は「セレクタ順序・プロパティ名+**値**の完全一致」(/tmp/r99/extract4.py — 意図した写像: veil 置換・fadeIn→mem-fade-in・glass-range 0.1→0.08・丸め 0.03→0.02×4/0.05→0.04×2/0.07→0.06×1 適用後、全6タブ IDENTICAL)。値の取り違え・沈黙欠落は機械証明で排除済み。
     射程外: `@media` の条件文字列は比較しない (内側の規則のみ)。現状は activity 640px の1つのみで条件一致を目視確認済み — @media が増えたら条件比較を追加すること。
     実行結果 (2026-11-20, 証跡):
     ```
     activity: rules 46 vs 46  IDENTICAL ✓
     knowledge_graph: rules 10 vs 10  IDENTICAL ✓
     memories: rules 58 vs 58  IDENTICAL ✓
     settings: rules 9 vs 9  IDENTICAL ✓
     timeline: rules 13 vs 13  IDENTICAL ✓
     wiki: rules 36 vs 36  IDENTICAL ✓
     ALL IDENTICAL ✓ — セレクタ順序・プロパティ名+値が完全一致
     ```
   - `npx vitest run` → **Test Files 37 passed (37) / Tests 373 passed (373)** (2026-11-20 実行)
   - 実ブラウザ (8793, dark + light) → **全項目確認済み** (2026-11-20 実行):
     - 配信 HTML: `<style>` 埋め込み **0個**、sections.css link は utilities.css 直後 (= 最後)
     - dark: glass-range の rangeBg = trackBg = `rgba(255,255,255,0.08)` (--veil-strong 解決)
     - light: `rgba(120,120,128,0.2)` (light テーマ値でトラックの溝が視認可能)
     - memories フォーム (form-textarea / glass-range / adv-search 6行) 正常描画、persona 2件ロード
   - **litmus test**: 幅760px で adv-search 行の gap = **12px 維持** (components.css:614-662 の dead 規則が生き返らないことを実測)
   - 作業ツリーは並行レーン (本体のコンフィグ化作業) と混在 → コミットは対象ファイルのみ明示 add

## 影響範囲

- 変更: variables.css / sections.css (新規) / base.py / sections/{activity,knowledge_graph,memories,settings,timeline,wiki}.py (計8ファイル)
- HTML クラス・JS ロジック・サーバ API は全て不変 (fadeIn→mem-fade-in の keyframes 名のみ例外)
- ユーザー可視差分: dark テーマでは大部分が知覚差ゼロ (丸め±0.01)。**例外**: glass-range トラックの 0.1→0.08 は輝度差 1.65% で知覚閾値超 (第2回 REVIEW 修正で意図的許容、light テーマの溝消失解消を優先)。batch bar の赤は彩度上昇 = 意図的。
  light テーマで白ベール部分が改善 (見えるようになる)
