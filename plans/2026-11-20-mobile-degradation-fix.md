# kanban #114 — components.css @media 767px の memories 規則が埋め込み後勝ちで死んでいる

## 病因 (EXPLORE 確定)

components.css:614-662 の `@media (max-width:767px)` ブロックのうち3セレクタが、
sections.css (旧 memories.py 埋め込み `<style>` の外部化先, #99) のベース規則と
**同詳細度・link 順後勝ち**で負けて一度も適用されていなかった:

| components.css (@media 767px) | sections.css ベース (link 順最後) | 死んだプロパティ |
|---|---|---|
| `.adv-search-row` L651 | L224 `gap:12px; align-items:center` | gap:6px, align-items:stretch (flex-direction:column は競争が無く生存) |
| `.adv-search-label` L659 | L225 `min-width:80px; font-size:0.78rem` | 両方 (min-width:auto, font-size:0.75rem) |
| `.mem-toolbar` L636 | L241 `gap:8px` | gap:6px (flex-wrap:wrap は同値ゆえ実害なし) |

競合が無く生きていた部分 (今回不変): `#mem-list .memory-card/.memory-compact`
(ID 詳細度), `#mem-search` (ID+!important), `.memory-card` tap highlight,
`.mem-toolbar .glass-btn/.glass-input` (0,2,0 で競合なし), `.view-toggle .view-btn` (0,2,0)。

## 判断 (judge): 有効化

削除ではなく有効化を選んだ。理由:
1. 規則の中身 (縦積み・ラベル自動幅・ツールバー間隔) はモバイル UX として設計意図が
   明白で、削除は意図を捨てるだけ。
2. 有効化のコストは @media ブロックを sections.css 側へ移すだけで、詳細度も
   順序も sections.css 内で完結する (ベース規則が同じファイル内なら @media が
   後で書かれるだけで順序勝ちになる)。

## 治療 (IMPLEMENT)

**sections.css** — memories ブロック末尾 (`.mem-compact-imp-fill` の直後) に追記:

```css
/* ── Mobile degradation (max-width 767px) ──
   Must live here, not components.css: sections.css is the last stylesheet,
   so these win by order over the equal-specificity base rules above ... */
@media (max-width: 767px) {
    .adv-search-row { flex-direction: column; align-items: stretch; gap: 6px; }
    .adv-search-row > .mode-btn-group { align-self: flex-start; }
    .adv-search-row .glass-input { width: 100%; }
    .adv-search-label { min-width: auto; font-size: 0.75rem; }
    .mem-toolbar { gap: 6px; }
}
```

- `.adv-search-row .glass-input { width:100% }` は元々 components.css 側で
  競合なし (生きていた) が、同じ @media の縦積みと一体を成すので一緒に移設した
  (sections.css 内で順序勝ち、computed 不変)。
- `.mem-toolbar` の `flex-wrap:wrap` は sections.css:241 が常に同値を持つため
  移設不要 (削除で喪失なし)。

**components.css** — 該当3ブロック+`width:100%` の1ブロックを削除し、跡地に
移設済みである旨のコメントを残した (kanban #114 参照)。
`@media` 内の他の memories 規則 (ID 系・tap 系・glass-btn 拡張・view-toggle) は
生きており component ベース規則との関係で同ファイル内が正しい位置なので残置。

## 検証 (TEST/GATE 実施済み)

- ブレースバランス (開=閉の一致のみが真実): components.css 337/337, sections.css 182/182。
- vitest 38 files 緑 (fail 0)。CSS は JS から独立で既存テストは触らない。
- 実ブラウザ (8793, CDP Emulation.setDeviceMetricsOverride, キャッシュバスト ?t=epoch + Network.setCacheDisabled):
  - **380px**: `.adv-search-row` = column / stretch / **gap 6px**、
    `.adv-search-label` = min-width auto / **12px** (0.75rem)、
    `.mem-toolbar` = **gap 6px** / wrap — 初適用は gap・align-items・label 2宣言・
    mem-toolbar gap の計5宣言 (flex-direction:column は元から競合なしで生存、
    病因表のとおり)。
  - **1280px**: `.adv-search-row` = row / center / 12px、`.adv-search-label` =
    80px / 12.48px、`.mem-toolbar` = 8px / wrap — デスクトップ完全不変 (回帰ゼロ)。
- **第1回 REVIEW (ルアン・メェイ BLOCK) 対応**: stretch 初適用で
  `.adv-search-row > .mode-btn-group` (枠付き flex, content 幅 273px) が
  cross-axis に引き伸ばされ「枠だけ伸びて中のボタンは左固まり」になる懸念を指摘された。
  対策として `@media` 内へ `.adv-search-row > .mode-btn-group { align-self: flex-start; }`
  の1行を追加。実測 (700px, row 幅 592px): group **273.094px に留まる** (align-self
  flex-start 効果)、`.glass-input` は width:100% で 592px 全幅 (意図どおり)。
  380px では group 273px ≒ 親幅 272px で視覚問題なし。デスクトップ 1280px では
  align-self:auto に戻ることを確認 (回帰ゼロ)。
- **FYI-2 (既存挙動、本 PR と無関係)**: `.adv-search-panel` 縦積みの実高は
  scrollHeight 584px < max-height 600px で切れず。
- 実測の前提: memories リストは `N.Features.Memories.loadMemories()` が
  observations 0 件だと empty-state で早期 return し toolbar を描画しない。
  GATE 用に `/api/memories/herta` へ fixture 1件を POST して描画させた
  (S.persona='herta' は token 認証直後の既定選択)。fixture は検証後 DELETE 済み。
  実測時の注意: `<link href="/static/styles/sections.css">` に query が無いため
  page reload だけでは旧 CSS が残る — Network.setCacheDisabled 必須。

### 第2回 REVIEW (PASS) 後の対応
- **NIT-1/2 (計画書の数値表記)**: ブレースは「開=閉の一致」のみを記録する形式に
  改めた (182/182)。行数表記も実測 (+15 / -17+3) に修正。
- **FYI-3 (.range-value の行幅中央浮き)**: `align-items: stretch` の副作用で
  Importance 行の数値が行中央に浮く。`@media` 内へ
  `.adv-search-row > .range-value { align-self: flex-start; }` の1行を追加し、
  実測 (320px): rv_align=flex-start, rv_x=49 でスライダー上に左揃い。
  700px でも rv_x=49 を確認 (デスクトップ 1280px は auto のまま回帰ゼロ)。
- **FYI-4 (320-360px で mode-btn-group 右端クリップ — 既存欠陥)**:
  `@media` 内の group 規則へ `max-width: 100%; flex-wrap: wrap;` を追加。
  実測 (320px, content 幅 212px): group_w=212 (max-width で制限)、
  group_right=261<320 → **クリップ解消**、wrap により 4ボタンが 2行
  (y=[1766,1795])、panel の scrollWidth 超過なし。
  実測 (700px): group_w=273 の自然幅で wrap しない (rows=1) — 広い画面での
  レイアウト不変。
  実測 (1280px): group/range-value とも auto — @media の外に宣言は存在しない。

## ファイル

- `nous/api/http/static/styles/sections.css` (+15: @media ヘッダ 7宣言のうち治療 6行 + range-value 1行)
- `nous/api/http/static/styles/components.css` (-17/+3: 死んだ 3ブロック削除 + 幕石コメント 3行)

## 残作業

REVIEW (ルアン・メェイ) → PASS → GATE → COMMIT → RECORD → PUSH → done。
