# #111: skeleton 経過秒表示 — loader fetch の 30s timeout 中の無反応 skeleton 改善

date: 2026-11-19
triage: 標準（コンポーネント単位・全タブ影響・UI 変更 → 実ブラウザ確認必須）

## 症状（カード #111 より）

settings 等の `-content` パネルは loader の fetch が終わるまで skeleton が居座る。
fetch には `AbortSignal.timeout(30000)`（api.js 既定）が掛かっており、サーバが遅いと
最悪30秒間 skeleton、その後 errorCard に落ちる。ユーザーには「固まった?」としか見えない。
出典: #93 第5回 REVIEW #6。

## EXPLORE の結論 — 修正案の取捨

カードの修正案3つのうち、(1) と (3) は**対応不要**、(2) を実装する。

- **(1) timeout 定数化: 達成済み。** `AbortSignal.timeout(30000)` は
  `core/api.js:10-11` の `N.Core.api` 既定値に一元化されている（#93 の出典 b34 以降、
  #106 の raw fetch 排除が完了）。features/ 配下に直書きは 0 件（grep 確認済み）。
  30s という数値は api.js の1箇所のみ。
- **(3) errorCard 共通化: 達成済み。** `N.Components.skeleton.errorCard(msg, retryFn)`
  （components/skeleton.js）が共通コンポーネントで、全8 loader がこれを使う
  （features/{activity,graph,projects,timeline,memories,overview,settings}）。
  文言と retry 先は loader 固有だが、遷移・DOM・retry delegation は共通。
- **(2) skeleton 経過秒表示: 未実装 → 本計画の本体。**

## 設計

`skeleton.show(tabId)` が panel に差し込む skeleton HTML の末尾に elapsed badge を包む:

```html
<div class="skeleton-elapsed" data-skeleton-elapsed>Loading…</div>
```

- `setInterval(1000)` で `Loading… Ns` に更新。開始時 `_elapsedStart = Date.now()`。
- **タイマー寿命は自動**: badge が panel 差し替えで DOM から消えたら
  `!badge.isConnected` を検知して `clearInterval`。ロード完了を loader 側で知る必要はない。
- **show() 再呼び出し**（タブ往復）は前タイマーを `clearInterval` してから新規開始
  （単一 `_elapsedTimer` 変数で十分 — 表示中 skeleton は1タブ分のみ）。
- selfManaged タブは show() が既に早期 return — 変更なし。register() のカスタム skeleton
  にも badge は付与される（show() 側で包むため）。
- CSS は `styles/components.css` の .skeleton 系ブロック（:100-106）の直後に追加:
  中央寄せ・`var(--text-muted)`・小さめ。shimmer（.skeleton::after）は継承しない。

### やらないこと（理由つき）

- **中断ボタン**: タブ切替で UI は即替わる（fetch は裏で継続するが操作は塞がらない）。
  専用ボタン + abortController の配線を全 loader に足す費用に見合わない。
- **timeout 時の errorCard 文言判別**（"timed out" vs "Failed to load"）: retry で復帰可能、
  経過秒で遅延は既に可視化される。8ファイル横断の catch 文言変更は費用>効果。
  shortcut: timeout 文言の区別は、ユーザーが実際に混乱すると申告されたら errorCard に
  e.name 判定を足すときに再検討。

## ファイルと変更規模

| ファイル | 変更 |
|---|---|
| `nous/api/http/static/components/skeleton.js` | show() に badge 付与 + `_startElapsed`（~20行） |
| `nous/api/http/static/styles/components.css` | `.skeleton-elapsed` 追加（~4行） |
| `nous/api/http/static/components/skeleton.test.js` | テスト4本追加（~45行） |

## テスト計画（skeleton.test.js 追加分）

1. show() 後、`[data-skeleton-elapsed]` が存在し "Loading…" から始まる
2. fake timers で1秒進めるとテキストが `Loading… 1s` になる
3. badge を DOM から消して timers を進めても例外なく停止する（isConnected ガード）
4. show() を2回呼ぶとカウントがリセットされる（前タイマー破棄の確認）

既存テストへの影響: `replaces non-self-managed content` などは innerHTML の包含判定で、
末尾に badge が増えても壊れない。

## 検証（TEST/GATE）

- `cd nous/api/http/static && npx vitest run` — 全緑（359+追加）
- 実ブラウザ確認（UI 変更の GATE 条件）: nous server を非同期起動 → browser-use で
  遅いタブの skeleton が表示され、経過秒が実時間で増えること・ロード完了で badge が消えることを確認。
  遅延の擬似は、overview 等のタブ遷移で十分（初回ロードの skeleton が見える）。
  30s 待つ必要は無い — 数秒で完了する通常ロードで「badge が現れて消える」ことを見る。
- **GATE 必須項目（REVIEW 指摘 #8）**: テスト環境は DOMPurify 無し＝safeSetHTML が textContent 分岐に落ち、badge が唯一の実要素になる。本番形状（実 div 群の後ろに badge）はブラウザでしか検証できない。(1) badge がパネルの**最後の要素**であること (2) ロード完了で badge が消えること — この2点を実機で確認する。

## REVIEW 観点（ルアン・メェイ）

- タイマー漏洩: show()→タブ切替→show() の往復で setInterval が積まないか
- isConnected ガードの到達性: badge が消えてもタイマーが止まるか
- register() カスタム skeleton への badge 付与が壊れないか
- 既存5テストの契約（selfManaged 則触らず）

## 進行

- [x] EXPLORE
- [x] PLAN（本書）
- [x] IMPLEMENT（直実装 — 規模小・委譲コスト不的釣合）
- [x] TEST（vitest 367 → REVIEW 対応後 369 passed）
- [ ] REVIEW（ルアン・メェイ 1回目 BLOCK 8件 → 全対応: #1 timerCount 拘束・#2 二重タイマー拘束・#3 60s 自滅・#4 selfManaged 切替で前タイマー停止・#5 skeleton-card 締め・#6 基準コメント・#7 aria-hidden・#8 GATE 条件明記）
- [ ] GATE（vitest 全緑 + 実ブラウザ確認 — 必須項目上記）
- [ ] COMMIT
- [ ] RECORD
