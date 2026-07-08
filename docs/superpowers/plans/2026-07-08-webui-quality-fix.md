# WebUI Quality Fix 実施計画

> **For agentic workers:** REQUIRED: Use @explorer for code discovery, @designer for UI/UX changes, @fixer for mechanical changes, @oracle for architecture decisions.

**Goal:** Nous WebUI のアクセシビリティ・パフォーマンス・UX の重大問題を修正し、プロダクション品質に引き上げる。

**Architecture:** フロントエンドは Python テンプレート（`sections/*.py`）+ 静的 JS/CSS（`static/`）による SPA。全変更は既存アーキテクチャを維持しつつ、レイヤーごとに実施。

**Tech Stack:** Starlette/FastMCP サーバー, Tailwind CSS（CDN）, Lucide icons, vis-network/vis-timeline, Chart.js, vanilla JS（S = グローバル状態）

**Chat サーバー動作確認結果:**
- SSE ストリーミング: ✅
- ツール呼び出し（memory_create）: ✅
- 設定保存/読込: ✅
- エラーハンドリング（空メッセージ）: ✅
- セッション/ロールバック: ✅
- コミットメント API: ✅

**→ サーバー側は問題なし。修正はすべてフロントエンド。**

---

## Chunk 1: P0 — アクセシビリティと安全性（Deadline: 最優先）

### Task 1: チャットアクションのキーボード到達性修正（WCAG 2.1.1）

**問題:** `.chat-msg-actions` が `:hover` のみで表示。キーボードユーザーは編集/再送/コピー/TTS ボタンに永遠に到達できない。

**Files:**
- Modify: `nous/api/http/static/chat.css`
- Modify: `nous/api/http/static/chat.js`（必要に応じて）

**修正内容:**
1. CSS に `:focus-within` フォールバックを追加
2. 各アクションに `tabindex="0"` を追加
3. ボタンに `role` と `aria-label` を明示

**現状:**
```css
.chat-msg-actions { opacity: 0; }
.chat-msg:hover .chat-msg-actions { opacity: 1; }
```

**修正後:**
```css
.chat-msg-actions { opacity: 0; }
.chat-msg:hover .chat-msg-actions,
.chat-msg:focus-within .chat-msg-actions { opacity: 1; }
```

**検証:**
- Tab でメッセージにフォーカス移動できること
- フォーカス中にアクションボタンが表示されること
- 各ボタンがキーボードで操作可能であること

---

### Task 2: 破壊的操作の確認ダイアログ追加

**問題:** 「会話をリセット」が確認なしで即時全メッセージ削除。データ消失リスク。

**Files:**
- Modify: `nous/api/http/static/chat.js`（`clearChatHistory()` 関数）

**修正内容:**
`clearChatHistory()` 内で `showConfirm()` を呼び、確認後にのみ削除実行。
```js
async function clearChatHistory() {
    if (CHAT.messages.length === 0) { resetToWelcome(); return; }
    const ok = await showConfirm('会話をリセット', '現在の会話履歴がすべて削除されます。よろしいですか？');
    if (!ok) return;
    // ... existing clear logic ...
}
```

**検証:**
- 「会話をリセット」押下で確認ダイアログ表示
- 「キャンセル」で何も起こらない
- 「OK」でメッセージが削除されウェルカム表示に戻る

---

### Task 3: CDN スクリプトのブロッキング解除

**問題:** 7 個の CDN スクリプトがすべて `<script>` でレンダリングブロッキング。FCP を直撃。

**Files:**
- Modify: `nous/api/http/sections/base.py`（`render_head()` 関数）

**修正内容:**
全 CDN スクリプトに `defer` を追加。重いライブラリ（Chart.js, vis-network, vis-timeline, highlight.js）は遅延読み込みに変更。

```python
# Before:
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>

# After:
<script src="https://cdn.tailwindcss.com" defer></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4" defer></script>
```

**追加: 遅延読み込みヘルパー（base.js）:**
```js
// タブ初回アクセス時に必要なライブラリを動的ロード
const LIB_LOADERS = {
    'analytics': () => loadScript('https://cdn.jsdelivr.net/npm/chart.js@4'),
    'timeline': () => Promise.all([
        loadScript('https://unpkg.com/vis-network/standalone/umd/vis-network.min.js'),
        loadScript('https://unpkg.com/vis-timeline/standalone/umd/vis-timeline-graph2d.min.js'),
    ]),
};
```

**検証:**
- ページ読み込みが明らかに速くなること
- 全タブで機能が正常動作すること

---

### Task 4: トースト通知に aria-live 追加

**問題:** `.toast-container` に `aria-live` がなく、スクリーンリーダーが新規トーストを読み上げない。

**Files:**
- Modify: `nous/api/http/sections/base.py`（トーストコンテナの HTML）

**修正内容:**
`role="status"` と `aria-live="polite"` をトーストコンテナに追加。
```html
<div class="toast-container" role="status" aria-live="polite" aria-atomic="true"></div>
```

---

### Task 5: 確認/警告モーダルのアクセシビリティ修正

**問題:** `showConfirm()` / `showAlert()` のモーダルがフォーカストラップ未実装、`role="dialog"` 未設定、日本語ハードコード。

**Files:**
- Modify: `nous/api/http/static/base.js`（`showConfirm()`, `showAlert()` 関数）
- Modify: `nous/api/http/static/base.css`（モーダル関連スタイル）

**修正内容:**
1. `role="dialog"`, `aria-modal="true"`, `aria-labelledby` 追加
2. フォーカストラップ実装（Tab/Shift+Tab をモーダル内に制限）
3. ESC キーでキャンセル扱い
4. オーバーレイ表示時に body のスクロールを防止

---

## Chunk 2: P1 — モバイル UX と基本アクセシビリティ

### Task 6: モバイル設定パネルのクローズ手段追加

**問題:** モバイルの設定パネルが固定オーバーレイなのに、閉じる X ボタンなし/スワイプなし/背景タップなし。

**Files:**
- Modify: `nous/api/http/sections/chat.py`（設定パネル HTML）
- Modify: `nous/api/http/static/chat.js`（`toggleSettingsPanel()`）
- Modify: `nous/api/http/static/chat.css`

**修正内容:**
1. 設定パネル上部に `×` 閉じるボタン追加
2. 背景オーバーレイをクリックで閉じる
3. ESC キーで閉じる

```html
<!-- 設定パネル先頭に追加 -->
<div class="settings-close-btn" onclick="toggleSettingsPanel()" aria-label="閉じる">
    <i data-lucide="x"></i>
</div>
```

---

### Task 7: スキップトゥコンテンツリンク追加

**問題:** キーボードユーザーが 11 タブ + ヘッダーコントロールをすべて Tab 通過しないと本文に到達できない。

**Files:**
- Modify: `nous/api/http/sections/base.py`

**修正内容:**
```html
<a href="#tab-content" class="skip-link" tabindex="0">メインコンテンツにスキップ</a>
```

```css
.skip-link {
    position: absolute; top: -100px; left: 16px;
    z-index: 1000; padding: 8px 16px;
    background: var(--accent-purple); color: white;
    border-radius: 4px; font-weight: 600;
}
.skip-link:focus { top: 16px; }
```

---

### Task 8: 絵文字アイコンを Lucide に置換

**問題:** 装備パネルや設定リンクで絵文字（👕👖👟⚙️）を構造的アイコンとして使用。プラットフォーム間で見た目が変わる。

**Files:**
- Modify: `nous/api/http/sections/chat.py`（装備ラベル、設定リンク）
- Modify: `nous/api/http/static/chat.js`（`updateEquipmentPanel()`）

**修正内容:**
- `⚙️ 設定パネルを開く` → `<i data-lucide="settings"></i> 設定パネルを開く`
- `👕上` → `<i data-lucide="shirt"></i> 上`
- `👖下` → `<i data-lucide="">` → 適切な Lucide アイコンに置換

---

## Chunk 3: P2 — コード品質とパフォーマンス

### Task 9: モーダル表示/非表示パターンの統一

**問題:** モーダルが 4 種類の異なる表示/非表示パターンで実装されている。

**Files:**
- Modify: `nous/api/http/static/base.css`
- Modify: `nous/api/http/static/base.js`（`showModal()` / `hideModal()` 共通関数）
- Modify: `nous/api/http/static/chat.js`（メモリ編集/詳細モーダル）
- Modify: `nous/api/http/static/coding_agent.js`

**修正内容:**
統一されたモーダル表示関数:
```css
.modal-overlay {
    display: flex; opacity: 0; visibility: hidden;
    transition: opacity 0.2s, visibility 0.2s;
}
.modal-overlay.active { opacity: 1; visibility: visible; }
```

```js
function showModal(selector) {
    const el = document.querySelector(selector);
    el.classList.add('active');
    document.body.style.overflow = 'hidden';
    trapFocus(el);
}
```

---

### Task 10: Lucide アイコン再生成の最適化

**問題:** タブ切替のたびに `lucide.createIcons()` が全 DOM を再スキャン。11 タブ分のアイコンを毎回再生成。

**Files:**
- Modify: `nous/api/http/static/base.js`（`switchTab()`）
- Modify: `nous/api/http/static/chat.js`（`appendChatMessage()` 等）

**修正内容:**
```js
// base.js switchTab()
lucide.createIcons({ attrs: { scope: panel } }); // 対象パネルのみ

// chat.js appendChatMessage() — アイコン追加時
const msgEl = ...; // 新規メッセージ要素
lucide.createIcons({ attrs: { scope: msgEl } }); // 新規要素のみ
```

---

### Task 11: コードブロック onclick インジェクションの安全化

**問題:** `renderCodeBlock()` が `onclick="sandboxRunBlock('+JSON.stringify(code)+',...)"` で XSS の可能性。

**Files:**
- Modify: `nous/api/http/static/chat.js`（`renderCodeBlock()`）

**修正内容:**
インライン `onclick` をやめ、`addEventListener` に変更。
```js
const btn = document.createElement('button');
btn.className = 'chat-code-run-btn';
btn.addEventListener('click', () => sandboxRunBlock(code, lang));
// インライン onclick 属性は使わない
```

---

### Task 12: 設定保存ボタンのローディング状態追加

**問題:** `saveChatConfig()` の保存中にスピナーや無効化がなく、連打で多重保存される。

**Files:**
- Modify: `nous/api/http/static/chat.js`（`saveChatConfig()`）

**修正内容:**
保存中はボタンを無効化 + テキスト変更:
```js
btn.disabled = true;
btn.textContent = '保存中...';
await fetch(...);
btn.disabled = false;
btn.textContent = '設定を保存';
```

---

## 検証手順（全タスク完了後）

```bash
# ruff チェック
ruff check nous/api/http/

# テスト実行
pytest tests/ -x -q

# 手動検証
python3 -m nous.main
# → ブラウザで http://localhost:26262 を開き以下を確認:
#   1. Tab キーでメッセージアクションに到達可能
#   2. 会話リセットに確認ダイアログが出る
#   3. トーストがスクリーンリーダーで読み上げられる
#   4. モーダル内にフォーカスが閉じ込められる
#   5. スキップリンクが最初の Tab で表示される
#   6. モバイル設定パネルが × ボタンで閉じられる
```

---

## 見送り項目（今回スコープ外）

| 項目 | 理由 |
|------|------|
| インラインスタイルの CSS 抽出 | 影響範囲が広大（全セクション + dashboard.py）、リグレッションリスク高。別計画で対応 |
| メモリパネルのモバイル対応 | UI 再設計が必要。タブ切替方式かドロワー方式か要検討 |
| タブオーバーフローのモバイル対応 | 11 タブの情報設計見直しが必要。設計判断を要する |
| `animateCards()` のリフロー改善 | 現状で許容範囲。パフォーマンス劣化が深刻化したら対応 |
| Chart.js フォールバック | 読み込み失敗自体が CDN 問題であり稀。エラーハンドリング追加のみで十分 |
