# WebUI Refactor Instructions
> **対象**: 実装モデル（人間または AI agent）向けの包括的リファクタリング指示書
> **前提計画**: `2026-07-15-webui-refactor.md`（Oracle レビュー由来の9フェーズ計画）
> **最終更新**: 2026-07-24（計画者回答反映済み、全 Q1-Q10 解決）

---

## 1. Objective

Nous Dashboard（`nous/api/http/` 配下）のフロントエンド WebUI を、保守性・安全性・ユーザビリティの観点から段階的にリファクタリングする。JS モジュール分割、Python テンプレート分割、CSS のモジュール化を含む包括的なリファクタリングを行い、後方互換アダプタを除去した最終状態に到達する。

---

## 2. Project Understanding

### 2.1 アーキテクチャ
| 層 | 技術 | 備考 |
|----|------|------|
| **サーバー** | Python 3.12+ / Starlette / FastMCP | `nous.main` → port 26262 |
| **HTML 生成** | Python 文字列連結（`sections/*.py`） | テンプレートエンジン不使用 |
| **CSS** | CSS3 Custom Properties | `base.css` (41KB) + `chat.css` (35KB)、ビルドステップなし |
| **JavaScript** | Vanilla JS + IIFE namespace パターン | 29ファイル、~400KB、バンドラー不使用 |
| **CDN 依存** | Tailwind CSS, Chart.js 4, marked+DOMPurify+hljs, lucide-icons, vis-network | `<script defer>` 読み込み |
| **状態管理** | グローバル `S` + `CHAT` オブジェクト + `Nous.Core.store`（二重化） | Pub/Sub 未完了 |

### 2.2 ファイル構成
```
nous/api/http/
├── sections/          # Python HTML テンプレート（文字列連結）
│   ├── base.py        # <html> シェル、<head>、ナビゲーション
│   ├── chat.py        # チャットタブ HTML（75KB — 最大ファイル）
│   └── *.py           # 各タブの HTML セクション
├── routers/           # REST API エンドポイント実装（62ルート）
├── static/            # 静的アセット
│   ├── core/          # 共通基盤（11ファイル）
│   ├── chat/          # チャット用モジュール（12ファイル）
│   ├── components/    # 空（再利用コンポーネント未抽出）
│   ├── features/      # 機能タブ — 未作成。現状は static/ 直下にモノリス JS
│   ├── base.js        # エントリポイント + タブ切り替え（707行）
│   ├── overview.js, memories.js, settings.js, # 機能タブ（モノリス、40-53KB）
│   │   graph.js, timeline.js, activity.js
│   ├── base.css       # デザインシステム + テーマ + オーブ背景（41KB）
│   └── chat.css       # チャット専用スタイル（35KB）
```

### 2.3 レンダリングフロー
1. `base.render_layout_shell()` → 完全な HTML を文字列連結で生成
2. `base.render_head()` → CDN スクリプト + `/static/` JS を `<script defer>` で読み込み
3. `base.render_nav(tabs)` → 動的ナビゲーションバー
4. 各 `sections/*.py` → `<div class="tab-content" id="tab-{name}">` を返す
5. クライアント側: `base.js` の `switchTab()` でタブ切り替え

---

## 3. Behaviors To Preserve

以下の動作・特性は変更してはならない：

| # | 保持項目 | 理由 |
|---|---------|------|
| 1 | **全タブの既存機能** | チャット（SSE ストリーミング、MCP ツール、TTS、画像生成、添付ファイル、メモリパネル）、Memories CRUD、タイムライン可視化、ナレッジグラフ、感情分析チャート、設定ホットリロード、ペルソナ管理、インポート/エクスポート、管理画面 |
| 2 | **ガラスモーフィズムデザイン** | CSS `backdrop-filter`, `box-shadow`, オーブ背景 — ダッシュボードの視覚的アイデンティティ |
| 3 | **SSE ストリーミングのリアルタイム性** | `chat.py` の `text/event-stream` と `events.py` のイベント配信 |
| 4 | **バックエンド非依存** | 既存 API エンドポイントのシグネチャ・レスポンス形式を変更しない |
| 5 | **CDN フォールバック** | CDN が切れた場合でも可能な限り機能劣化で済むよう配慮 |
| 6 | **モバイルレスポンシブ** | 既存のメディアクエリベースの応答性を維持（本計画で本格的に強化） |
| 7 | **ペルソナ切り替え** | ナビバーのペルソナセレクター機能を維持 |
| 8 | **テーマ切り替え（ダーク/ライト）** | CSS Variables によるテーマシステムを維持 |

---

## 4. Non-Negotiables（絶対的制約）

| # | 制約 | 説明 |
|---|------|------|
| **N1** | **バンドラー導入禁止** | Vite/Webpack/esbuild 等の導入は本計画の範囲外。Vanilla JS を維持する。 |
| **N2** | **バックエンド API 変更禁止** | `nous/api/http/routers/` 配下のルーターのシグネチャ変更・削除は不可。追加は可能。 |
| **N3** | **テンプレートエンジン導入禁止** | Jinja2 等への移行は行わない。ただし Python 側の文字列連結の整理（ファイル分割、リスト結合への変更等）は許容する。 |
| **N4** | **テスト破壊禁止** | 既存の全テスト（`tests/unit/` + `static/**/*.test.js`）は常に PASS 状態を維持する。 |
| **N5** | **後方互換をフェーズ間で維持** | 各フェーズ完了後、全機能が正常動作すること。不完全な状態でのフェーズ完了は禁止。 |
| **N6** | **1フェーズ = 1コミット** | 各フェーズは単一の atomic コミットにまとめる。 |
| **N7** | **CI グリーン状態の維持** | 全フェーズ完了時、`pytest tests/unit/` + `npm test`（vitest）がグリーンであること。 |
| **N8** | **TypeScript 移行禁止** | 本計画では行わない。型の恩恵が必要なら JSDoc アノテーションで代用。 |

---

## 5. Stop And Ask Conditions（停止・確認条件）

以下の状況では実装を停止し、計画者に確認すること：

| # | 条件 | 確認内容 |
|---|------|---------|
| **S1** | 単一モジュールが予想の 2 倍以上の規模になった | 分割方針の再検討 |
| **S2** | 既存機能の動作が意図せず変更された | ロールバックか回避策の判断 |
| **S3** | テストが通らない原因が特定できない（30分以上） | アプローチの再評価 |
| **S4** | グローバル変数 `S` / `CHAT` / `window.*` の削除で依存元が特定不能 | 依存マップの再調査 |
| **S5** | クロスブラウザ問題が発覚した（特に Safari/Firefox） | 既知の対応策の確認 |
| **S6** | 変更が 3 フェーズ以上にまたがると判断 | フェーズ分割の見直し |
| **S7** | モジュール分割時に循環参照が発生 | 依存方向の再設計 |

---

## 6. Baseline Commands（品質確認コマンド）

リファクタリング前後で必ず実行し、差分がないことを確認する：

```bash
# === Python テスト ===
pytest tests/unit/ -q --timeout=60
# 期待出力: 全 PASS（`passed` 数が減少しないこと）

# === JS テスト ===
cd nous/api/http/static && npm test
# 期待出力: 全 PASS（`Tests  x passed` が減少しないこと）

# === Lint ===
ruff check nous/ tests/
ruff format --check nous/ tests/
cd nous/api/http/static && npm run lint:css

# === 型チェック（存在する場合のみ） ===
mypy nous/ 2>/dev/null || true

# === サーバー起動確認 ===
curl -f http://localhost:26262/health
# 期待: 200 OK + JSON レスポンス

# === ダッシュボード表示確認 ===
curl -s http://localhost:26262/ | head -c 100
# 期待: <!DOCTYPE html> で始まる完全な HTML
```

---

## 7. Debt Map（技術的負債マップ）

### 7.1 重大度: HIGH（独立フェーズ化されている）

| ID | 場所 | 内容 | 対応フェーズ |
|----|------|------|------------|
| **D1** | `base.js:6-14` + `chat-core.js:38` | **二重状態システム**: グローバル `S` と `Nous.Core.store` が共存し、同期が不完全。 | P2 |
| **D2** | `base.js:19-24` + 全モジュール | **グローバル `window` 汚染**: 全モジュールが `N.*` と `window.*` の両方にエクスポート。 | P12 |
| **D3** | `sections/chat.py` (75,728 bytes) | **Python テンプレート肥大化**: チャットタブ HTML 生成がモノリス。 | P7 |
| **D4** | `overview.js` (42KB), `settings.js` (53KB), `memories.js` (41KB) | **機能タブ JS モノリス**: 定数重複、`S` 直接参照、モジュール分割未実施。 | P1 + P6 |

### 7.2 重大度: MEDIUM

| ID | 場所 | 内容 | 対応フェーズ |
|----|------|------|------------|
| **D5** | `base.js:246-258` | **`showSkeleton()` のハードコードブラックリスト**: タブ名で分岐。 | P5 |
| **D6** | `sections/base.py:112-173` | **`.replace()` エスケープの脆弱性**: HTML エスケープに `str.replace()` 使用。 | P4 |
| **D7** | `static/components/` | **空ディレクトリ**: コンポーネント抽出の設計があり未実装。 | P5 |
| **D8** | `lefthook.yml:5` | **古いパス参照**: `memory_mcp/` → `nous/` に修正が必要。 | P0 |
| **D9** | `base.css` (41KB) + `chat.css` (35KB) | **CSS モノリス**: デッドコード、重複、変数未統一の可能性。 | P8 |

### 7.3 重大度: LOW

| ID | 場所 | 内容 | 対応フェーズ |
|----|------|------|------------|
| **D10** | CI (`ci.yml`) | **統合テストが CI 未実行**: httpx 統合テストが CI パイプラインに含まれていない。 | P14 |
| **D11** | `base.py:143` | **バージョンハードコード**: `__version__` 直接参照。 | P15 |
| **D12** | `routers/admin.py:90` | **再構築の排他制御不足**: 並行実行で DB 不整合リスク。 | 範囲外（バックエンド） |
| **D13** | `routers/events.py:84` | **キューサイズ上限なし**: 高負荷時メモリリークの可能性。 | 範囲外（バックエンド） |

---

## 8. Implementation Phases

各フェーズは独立して完了・テスト可能であること。依存関係はフェーズ番号で示す。
各フェーズ完了時に Baseline Commands（Section 6）を実行し、PASS を確認すること。

---

### Phase 0: Fix Known Bugs

**依存**: なし
**見積**: 1 ファイル、5 分

**内容**: `lefthook.yml` の `memory_mcp/` → `nous/` に修正（D8）。

**対象ファイル**:
- `lefthook.yml`

**受入基準**:
- [ ] `lefthook.yml` が `nous/` を参照する
- [ ] pre-commit hook が正常動作する

---

### Phase 1: Feature Files Consume `Nous.Core.*` Constants

**依存**: Phase 0
**見積**: 6 ファイル、30 分

**内容**: 各機能タブファイルが `N.Core.CHART_COLORS`, `N.Core.EMOTION_COLORS`, `N.Core.BODY_*` 等を参照するよう修正。ローカルの重複定数定義を削除する（D4 軽減）。不足定数は `constants.js` に追加。

**対象ファイル**:
| ファイル | 重複定数 | 置換元 |
|---------|---------|--------|
| `overview.js` | `CHART_COLORS`, `EMOTION_COLORS`, emotion bar colors | `N.Core.*` |
| `settings.js` | chart 関連定数 | `N.Core.*` |
| `memories.js` | emotion colors | `N.Core.EMOTION_COLORS` |
| `graph.js` | graph colors | `N.Core.*` |
| `timeline.js` | timeline colors | `N.Core.*` |
| `activity.js` | 該当するものがあれば | `N.Core.*` |
| `core/constants.js` | — | 不足定数を追加 |

**手順**:
1. 各ファイルのローカル定数定義を特定（grep `const.*=`）
2. `N.Core.*` が同名で利用可能か確認（`constants.js` と突合）
3. 不足している定数を `constants.js` に追加
4. 各ファイルのローカル定義を削除し `N.Core.*` 参照に置換
5. `npm test` + ダッシュボード表示確認

**受入基準**:
- [ ] 全機能タブにわたって重複定数定義が 0 件
- [ ] `npm test` PASS
- [ ] 全タブの表示がリファクタリング前と同一

---

### Phase 2: Complete Pub/Sub Store Integration

**依存**: Phase 1
**見積**: 5-8 ファイル + テスト追加、1.5 時間

**内容**: `S` オブジェクトと `Nous.Core.store` 間の二重状態を解消する（D1）。全モジュールが store 経由で読み取り + subscribe を行う。**store.test.js のテストカバレッジを拡充する**（エッジケース: 複数購読解除、存在しないキーの取得、循環参照防止）。

**対象ファイル**:
| ファイル | 変更内容 |
|---------|---------|
| `core/store.js` | Pub/Sub の完成確認 + 必要なら補完（`subscribe`, `notify`, `get`, `set`） |
| `core/store.test.js` | テスト拡充: 複数 subscriber、unsubscribe の分離、存在しないキー、ネストキー |
| `base.js` | `S` → `N.Core.store` への一方向同期を双方向同期に拡張 |
| `chat-core.js` | `CHAT` / `N.Chat.state` を store に統合 |
| `chat-settings.js` | `S.persona` → `store.get('persona')` |
| その他 `S` / `CHAT` 直接参照があるファイル | 同様に置換 |

**手順**:
1. `core/store.js` の `subscribe()` / `notify()` / `get()` / `set()` の動作検証
2. `core/store.test.js` にテストケース追加（全 edge case 網羅）
3. `npm test` で PASS 確認
4. `base.js` の `S` → store ミラーリング（345-363行）を双方向同期に拡張
5. 各ファイルの `S.xxx` 参照を 1 つずつ `N.Core.store.get('xxx')` に置換
6. `CHAT` オブジェクト参照も同様に store 経由に
7. 各置換後に全タブ動作確認

**受入基準**:
- [ ] `S` の直接読み取りがアダプター層（`base.js`）のみ
- [ ] `CHAT` の直接読み取りが `chat-core.js` の store 同期コードのみ
- [ ] `store.test.js` が全 edge case をカバー（`npm test -- --coverage` で store.js が 90%+）
- [ ] `npm test` PASS
- [ ] チャットストリーミング正常動作

---

### Phase 3: DOM Rendering Safety

**依存**: Phase 2
**見積**: 全 `innerHTML` 該当箇所（grep 後特定）、1.5 時間

**内容**: `innerHTML` 代入を安全なパターンに置換。`dom.js` にヘルパーを追加。

**手順**:
1. `innerHTML` 使用箇所を grep で全列挙（JS + Python sections の全ファイル）
2. 各箇所を評価:
   - 単純テキスト挿入 → `textContent` に置換
   - HTML 挿入が必要 → `DOMPurify.sanitize()` 経由を確認
   - 構造生成 → `createElement` + `appendChild` に置換
3. `dom.js` に `safeSetHTML(element, html)` ヘルパー追加（`DOMPurify.sanitize` ラッパー）

**受入基準**:
- [ ] `innerHTML` の未保護使用が 0 件（DOMPurify 経由は許容）
- [ ] チャットの Markdown レンダリング正常（コードブロック、テーブル、画像）
- [ ] 全タブの DOM 表示がリファクタリング前と同一
- [ ] `npm test` PASS

---

### Phase 4: Template Escape Safety（Python 側エスケープ修正）

**依存**: Phase 3
**見積**: `sections/base.py` + 影響ファイル、1 時間

**内容**: D6 対応。`sections/base.py:112-173` の `.replace()` による HTML エスケープを `html.escape()` に置換し、`render_layout_shell()` および関連するセクションの HTML 生成の安全性を向上させる。

**対象ファイル**:
| ファイル | 変更内容 |
|---------|---------|
| `sections/base.py` | `.replace('&', '&amp;').replace('<', '&lt;')...` → `html.escape()` |
| `sections/chat.py` 他 | `base.py` のエスケープ関数を使っている箇所の一貫性確認 |

**手順**:
1. `sections/base.py` のエスケープパターンを特定（`str.replace` チェーン）
2. `import html` を追加し `html.escape(value, quote=True)` に置換
3. 全 sections ファイルのエスケープ方式が統一されているか確認
4. ダッシュボード表示確認（特殊文字を含むペルソナ名・メモリ内容でテスト）

**受入基準**:
- [ ] `sections/base.py` に `.replace()` チェーンによるエスケープが存在しない
- [ ] 全 sections ファイルで `html.escape()` が使用されている
- [ ] 特殊文字（`<>&"'`）を含むデータでダッシュボードが正常表示
- [ ] `pytest tests/unit/` PASS

---

### Phase 5: Component Extraction

**依存**: Phase 4
**見積**: 5-7 ファイル、2 時間

**内容**: `static/components/` を実体化する（D7）。skeleton, memory-card, chart の 3 コンポーネントを抽出し、さらに機会駆動で共有 UI（modal, toast, tab-navigation）もコンポーネント化する。`showSkeleton()` のハードコードブラックリスト（D5）も解消。

**新規作成ファイル**:
| ファイル | 内容 |
|---------|------|
| `static/components/skeleton.js` | `skeletonCard()`, `errorCard()`, `emptyState()`, `showSkeleton()` 汎用版 |
| `static/components/memory-card.js` | `openMemModal()`, `renderBodyStateBars()`, `renderEmotionBars()` / `renderEmotionBadges()` |
| `static/components/chart.js` | `chartOpts()`, `destroyChart()`（`base.js:576` から抽出） |
| `static/components/modal.js` | **機会駆動**: `showConfirm()`, `showAlert()` を `core/modal.js` から拡張 |
| `static/components/toast.js` | **機会駆動**: toast 表示の UI コンポーネント化 |
| `static/components/tab-nav.js` | **機会駆動**: タブナビゲーションのレンダリングロジック抽出 |

**修正ファイル**:
| ファイル | 変更内容 |
|---------|---------|
| `base.js` | skeleton/error/chart を components からの import に置換（D5 ブラックリスト除去） |
| `overview.js` | `N.Components.*` 使用 |
| `settings.js` | 同上 |
| `memories.js` | `N.Components.memoryCard()` 使用 |
| `sections/base.py` | 新規コンポーネント JS の `<script defer>` 読み込み追加 |

**受入基準**:
- [ ] `static/components/` に少なくとも 3 ファイルが存在
- [ ] `showSkeleton()` にハードコードブラックリストが存在しない
- [ ] 全タブの skeleton ローディング・エラー表示が正常
- [ ] `npm test` PASS

---

### Phase 6: Feature File Sub-Module Splitting

**依存**: Phase 5
**見積**: 大規模（3 ファイルのモジュール分割）、3-4 時間

**内容**: Q1 回答（ベストプラクティスに基づく許可）に基づき、機能タブのモノリス JS ファイルを `chat/` 同様にサブモジュール分割する。

**分割計画**:

| 現ファイル (サイズ) | 分割先 (`static/features/{name}/`) |
|---------------------|-----------------------------------|
| `overview.js` (42KB) | `overview-core.js`（状態、初期化）, `overview-stats.js`（統計カード）, `overview-charts.js`（感情チャート）, `overview-context.js`（コンテキスト表示） |
| `settings.js` (53KB) | `settings-core.js`（状態、初期化）, `settings-form.js`（フォームレンダリング）, `settings-save.js`（保存ロジック）, `settings-validation.js`（バリデーション） |
| `memories.js` (41KB) | `memories-core.js`（状態、初期化）, `memories-list.js`（一覧表示・ページネーション）, `memories-edit.js`（編集モーダル）, `memories-search.js`（検索・フィルタ） |
| `graph.js` (16KB) | サイズが小さいため `features/graph.js` に移行のみ |
| `timeline.js` (11KB) | サイズが小さいため `features/timeline.js` に移行のみ |
| `activity.js` (9KB) | サイズが小さいため `features/activity.js` に移行のみ |

**手順**:
1. `static/features/` ディレクトリ作成
2. `graph.js`, `timeline.js`, `activity.js` を `features/` に移動し namespace を `N.Features.*` に変更
3. `overview.js` を 4 モジュールに分割（依存関係: core → stats/charts/context）
4. `settings.js` を 4 モジュールに分割
5. `memories.js` を 4 モジュールに分割（最大の分割）
6. `sections/base.py` の `<script>` 読み込みパスを全更新
7. `sections/*.py` の各タブ HTML の参照先を更新（必要な場合）

**受入基準**:
- [ ] `static/features/` に全サブモジュールが存在
- [ ] 各サブモジュールが `N.Features.{Tab}.*` に正しく登録される
- [ ] `sections/base.py` の JS 読み込みが全サブモジュールをカバー
- [ ] 全タブ正常動作（タブ切り替え、データ読み込み、CRUD 操作）
- [ ] `npm test` PASS

---

### Phase 7: Python Template Split — `sections/chat.py`

**依存**: Phase 6
**見積**: `sections/chat.py` のサブモジュール分割、2-3 時間

**内容**: Q6 回答に基づき、75KB の `sections/chat.py` を機能単位のサブモジュールに分割する。Python の文字列連結方式は維持しつつ、ファイル分割で保守性を向上させる。

**分割計画**:

| 現状 | 分割先 (`sections/chat/`) |
|------|--------------------------|
| `sections/chat.py` (75KB) | `__init__.py`（`render_chat_tab()` の統合） |
| | `chat_layout.py`（チャットコンテナ、メッセージエリア、入力エリアの HTML） |
| | `chat_sidebar.py`（設定サイドバー: provider, MCP, TTS, 画像生成設定） |
| | `chat_memory_panel.py`（メモリパネル HTML） |
| | `chat_attachments.py`（添付ファイルアップロード HTML） |
| | `chat_modals.py`（各種モーダル: ツール詳細、画像生成等） |
| | `chat_scripts.py`（チャット用 `<script>` タグ群） |

**手順**:
1. `sections/chat/` パッケージディレクトリを作成し `__init__.py` を配置
2. `chat.py` の HTML ブロックを機能ごとに切り出し（文字列連結のまま各サブモジュールに移動）
3. 各サブモジュールが `render_chat_*()` 関数をエクスポート
4. `__init__.py` が全サブモジュールを呼び出し `render_chat_tab()` として統合
5. `dashboard.py` / `base.py` の `chat.py` 参照を `chat/` パッケージに更新
6. 全インポートパスの更新とテスト

**受入基準**:
- [ ] `sections/chat/` パッケージが存在し、`__init__.py` が `render_chat_tab()` をエクスポート
- [ ] 元の `sections/chat.py` が削除されている
- [ ] チャットタブの全機能が正常（SSE ストリーミング、設定変更、メモリパネル、添付ファイル）
- [ ] `pytest tests/unit/` PASS

---

### Phase 8: CSS Refactoring

**依存**: Phase 7
**見積**: `base.css` + `chat.css` のモジュール化、2-3 時間

**内容**: Q5 回答に基づき、`base.css` (41KB) と `chat.css` (35KB) を整理する。デッドコード除去、CSS Variables の統一、関心ごとのファイル分割を行う。

**分割計画**:

| 現状 | 分割先 (`static/styles/`) |
|------|--------------------------|
| `base.css` (41KB) | `variables.css`（CSS Custom Properties 全定義） |
| | `reset.css`（リセット / ベーススタイル） |
| | `layout.css`（グリッド、ナビゲーション、タブレイアウト） |
| | `theme.css`（ガラスモーフィズム、オーブ背景、ダーク/ライトテーマ） |
| | `components.css`（ボタン、カード、モーダル、トースト、フォーム） |
| `chat.css` (35KB) | `styles/chat.css`（チャットメッセージ、入力エリア、設定パネル） |
| | `styles/chat-mobile.css`（チャットのモバイル向けオーバーライド） |

**手順**:
1. `static/styles/` ディレクトリ作成
2. CSS Variables を全収集 → `variables.css` に統合。重複する変数定義を 1 つに
3. `base.css` を関心ごとに 5 ファイルに分割
4. `chat.css` を 2 ファイルに分割
5. `sections/base.py` の `render_head()` で新しい CSS ファイルを `<link>` で読み込み
6. スタイルのデッドコードを除去（未使用クラス・重複ルール）
7. `npm run lint:css` で検証

**受入基準**:
- [ ] `static/styles/` に CSS ファイルが存在し、`render_head()` で読み込まれている
- [ ] CSS ファイルの合計サイズがリファクタリング前より減少している
- [ ] 全タブの表示がリファクタリング前とピクセルレベルで同一
- [ ] `npm run lint:css` PASS
- [ ] Playwright ビジュアルテスト（`test_homepage_desktop`）が PASS または許容範囲内

---

### Phase 9: Usability Hardening — Loading / Empty / Error States

**依存**: Phase 8
**見積**: 全機能タブの状態ハンドリング追加、2 時間

**内容**: 全タブでローディング・空・エラーの 3 状態を明示的にハンドリングする。Phase 5 のコンポーネントを使用する。

**対象**:
| タブ | 必要な状態ハンドリング |
|------|----------------------|
| overview.js | stats 読み込み中（skeleton）/ 空 / API エラー |
| memories.js | 一覧読み込み中 / 検索結果ゼロ / API エラー |
| settings.js | 設定読み込み失敗 / 保存失敗 |
| graph.js | グラフデータ空 / vis-network 読み込み失敗 |
| timeline.js | タイムラインデータ空 / vis-timeline 読み込み失敗 |
| activity.js | アクティビティログ空 / イベント読み込み失敗 |
| chat-history.js | 履歴空 / 読み込み失敗 |

**手順**:
1. 各ファイルの API 呼び出し箇所を特定
2. レスポンスがない/エラーの場合の分岐を追加
3. `N.Components.emptyState()` / `N.Components.errorCard()` で表示
4. エラー時はリトライボタン（再フェッチ）を提供

**受入基準**:
- [ ] 全タブで 3 状態が明示的にハンドリングされている
- [ ] ネットワークエラー時に空タブや無限スピナーが表示されない
- [ ] エラー状態のリトライボタンが動作する

---

### Phase 10: Usability Hardening — Keyboard Accessibility

**依存**: Phase 9
**見積**: 複数ファイル、1.5 時間

**内容**: 主要インタラクションのキーボード到達性を確保する。

**対象**:
| 項目 | 内容 |
|------|------|
| タブ切り替え | `Tab` / `Shift+Tab` でナビゲーション移動、`Enter` / `Space` で選択、`role="tablist"` / `role="tab"` |
| モーダル | フォーカストラップ、`Escape` で閉じる、`role="dialog"` / `aria-modal="true"` |
| チャット入力 | 常にキーボード到達可能、`Enter` 送信 / `Shift+Enter` 改行 |
| メモリカード | `Tab` でカード間移動、`Enter` で詳細 |
| トースト通知 | `aria-live="polite"` / `role="status"` |
| スキップリンク | 「メインコンテンツへスキップ」リンクの動作確認 |

**受入基準**:
- [ ] キーボードのみで全主要機能に到達・操作可能
- [ ] モーダル表示中は背後要素にフォーカスが移動しない
- [ ] `Escape` で全モーダルが閉じる

---

### Phase 11: Mobile Responsiveness（本格的対応）

**依存**: Phase 10
**見積**: CSS + JS + Python sections 調整、3-4 時間

**内容**: Q2 回答（本格的対応）に基づき、全タブのモバイル UX を強化する。390×844 をベースラインとし、768px 未満の全ビューポートで最適化する。

**対象**:
| 項目 | 内容 |
|------|------|
| ナビゲーション | ハンバーガーメニュー（`aria-expanded` 付き）、スワイプ閉じ |
| チャット設定パネル | 全画面オーバーレイ、上部に閉じるボタン + タイトルバー |
| テーブル（skills, admin, import/export） | 横スクロール + カードビューフォールバック |
| メモリカード | 1 カラムレイアウト、タップターゲット 44×44px 以上 |
| タイムライン/グラフ | vis-* ライブラリのレスポンシブオプション設定、タッチ操作対応 |
| トースト | 画面下部固定、全幅に近いサイズ、スワイプで消去 |
| フォーム（settings, persona edit） | ラベルをフィールド上部に配置、全幅入力 |
| ペルソナセレクター | ドロップダウンのタップ領域拡大 |

**手順**:
1. `static/styles/` にモバイル用 CSS を追加（`responsive.css` 等）
2. 各タブの JS でモバイル検出（`matchMedia('(max-width: 767px)')`）と適応ロジック
3. Python sections 側でモバイル向け HTML 構造の調整が必要な箇所を修正
4. Playwright モバイルテスト（`test_homepage_mobile`）で検証
5. 実機エミュレーション（Chrome DevTools）でタッチ操作確認

**受入基準**:
- [ ] Playwright モバイルテストが視覚的に破綻していない
- [ ] 全タブが 390×844 でスクロール可能かつ全機能にアクセス可能
- [ ] 主要ボタン/リンクのタップターゲットが 44×44px 以上
- [ ] ハンバーガーメニューが開閉可能
- [ ] フォーム送信がモバイルで正常動作

---

### Phase 12: Remove Window Pollution

**依存**: Phase 11
**見積**: 複数ファイル（grep 後特定）、2 時間

**内容**: 全モジュールの `window.*` エクスポートを除去し、`N.*` 名前空間のみに統一する（D2）。最もリスクの高いフェーズ — HTML（`sections/*.py`）のインライン `onclick` に `window.*` 参照が残っている可能性がある。

**手順**:
1. `window.` の使用箇所を grep で全列挙（JS + Python sections ファイル両方）
2. `window.foo = foo` パターン（エクスポート）を特定し削除
3. `sections/*.py` 内の `onclick="window.foo()"` → `onclick="N.Module.foo()"` に置換
4. `<script>` 内の `window.*` 参照も同様に `N.*` に置換
5. 完全に除去できない `window.*` は一箇所に集約し `@deprecated` コメント付きで残す

**受入基準**:
- [ ] `window.` エクスポートが deprecated マーク付きの最小限を除き 0 件
- [ ] 全タブのクリックイベント・フォーム送信が正常動作
- [ ] `npm test` PASS

---

### Phase 13: Remove Backward Compat Adapter

**依存**: Phase 12
**見積**: 2-3 ファイル、30 分

**内容**: Phase 12 で `window.*` 参照が全除去されたことを確認後、`base.js` の後方互換アダプターコードを削除する。

**対象**:
| ファイル | 削除対象 |
|---------|---------|
| `base.js` | `var` エイリアス（19-24行付近）、非推奨の `window.*` マッピング |

**受入基準**:
- [ ] `base.js` に後方互換目的のコードが残っていない
- [ ] 全タブ正常動作
- [ ] `npm test` + `pytest tests/unit/` PASS

---

### Phase 14: Integration Tests in CI

**依存**: Phase 13
**見積**: CI 設定 1 ファイル、1 時間

**内容**: D10 対応。`tests/integration/` を CI パイプラインに追加する。**UI テスト（Playwright）は手動実行のまま CI には追加しない**（Q3 回答に基づく）。

**対象**:
| ファイル | 変更内容 |
|---------|---------|
| `.github/workflows/ci.yml` | `integration` job 追加（httpx + ASGI transport） |

**手順**:
1. CI 設定に統合テスト job を追加
2. サーバー起動 → `pytest tests/integration/` → サーバー停止のフロー
3. Playwright のブラウザインストールは不要（UI テストは実行しないため）

**受入基準**:
- [ ] CI パイプラインに統合テスト job が存在し PASS
- [ ] PR マージブロックが正常に機能する
- [ ] UI テストは CI で実行されない（手動実行用コマンドが README 等に記載されている）

---

### Phase 15: Final Cleanup & Documentation

**依存**: Phase 14
**見積**: ドキュメント + 残タスク、1 時間

**内容**: 残存する軽微な負債の解消、ドキュメント類の更新。

**対象**:
| 項目 | 内容 |
|------|------|
| 残存 `@deprecated` マーク | Phase 12 で残したエイリアスの最終除去可否を判断 |
| `docs/llm_usage_guide.md` | 古い API 名参照の修正（`memory()` → `memory_create`/`memory_read` 等） |
| `CLAUDE.md` | 新規ファイル構成の反映 |
| `AGENTS.md` | 本リファクタリング後の開発ガイドライン更新（必要な場合） |
| コード内コメント | 全フェーズで追加した TODO/FIXME/DEPRECATED コメントの棚卸し |

**受入基準**:
- [ ] 全 @deprecated マークが解決済みまたは理由付きで残存
- [ ] `docs/` の関連ドキュメントが新構成を反映
- [ ] `npm test` + `pytest tests/unit/` + `pytest tests/integration/` 全 PASS

---

## 9. Verification Requirements（検証要件）

### 9.1 フェーズ完了時確認（必須）

各フェーズ完了後、以下を実施し PASS を確認すること：

| # | 検証項目 | 方法 |
|---|---------|------|
| V1 | Python 単体テスト | `pytest tests/unit/ -q --timeout=60` |
| V2 | JS テスト | `cd nous/api/http/static && npm test` |
| V3 | Python lint | `ruff check nous/ tests/` |
| V4 | CSS lint | `cd nous/api/http/static && npm run lint:css` |
| V5 | サーバー起動 | `curl -f http://localhost:26262/health` → 200 OK |
| V6 | ダッシュボード表示 | `curl -s http://localhost:26262/` → `<!DOCTYPE html>` |
| V7 | 手動スモークテスト | ブラウザで: チャット送信、タブ切り替え、メモリ作成、グラフ表示 |

### 9.2 特定フェーズ追加検証

| フェーズ | 追加検証項目 |
|---------|------------|
| P2 | `npm test -- --coverage` で store.js カバレッジ 90%+ |
| P6 | 分割後の各サブモジュールが単独で読み込めること（コンソールエラーなし） |
| P7 | `sections/chat/__init__.py` の `render_chat_tab()` が元の `render_chat_tab()` と同一の HTML を返すこと |
| P8 | Playwright デスクトップテストで visual diff が閾値内（`max_diff_pixels=100`） |
| P11 | Playwright モバイルテストで visual diff が閾値内 |
| P12 | `window.*` エクスポートの grep 結果が期待通り減少 |

### 9.3 最終検証（Phase 15 完了時）

| # | 検証項目 | 方法 |
|---|---------|------|
| V8 | 統合テスト | `pytest tests/integration/` → PASS |
| V9 | JS 総サイズ | `du -sh static/**/*.js` が ±15% 以内 |
| V10 | CSS 総サイズ | リファクタリング前より減少していること |
| V11 | 画面読み込み時間 | リファクタリング前と ±20% 以内 |

---

## 10. Reporting Format（報告フォーマット）

各フェーズ完了時、以下のフォーマットで報告すること：

```
## Phase N: [フェーズ名] — COMPLETE

### 変更ファイル
- `path/to/file.js` — [変更内容の1行説明]
- ...

### テスト結果
- pytest: X passed, Y skipped, Z failed
- vitest: X passed
- lint: PASS / FAIL（失敗時は修正内容）

### スモークテスト
- [ ] チャット送信
- [ ] タブ切り替え（全タブ）
- [ ] メモリ CRUD（作成・編集・削除）
- [ ] グラフ表示（knowledge graph + 感情チャート）
- [ ] 設定変更 + 保存

### 備考
- [気づいたこと、次のフェーズへの注意点、残った懸念事項]
```

---

## 11. Out-of-scope Items（範囲外）

以下は本リファクタリングの範囲外：

| # | 項目 | 理由 |
|---|------|------|
| O1 | **バンドラー（Vite/Webpack等）導入** | Non-Negotiable N1 |
| O2 | **TypeScript 移行** | Non-Negotiable N8 |
| O3 | **テンプレートエンジン（Jinja2等）導入** | Non-Negotiable N3 |
| O4 | **CSS フレームワーク変更**（Tailwind 以外） | 影響範囲過大 |
| O5 | **新機能追加** | 本計画は純粋なリファクタリング |
| O6 | **バックエンドロジック変更** | Non-Negotiable N2 |
| O7 | **CDN 依存のバンドル化** | セキュリティ要件が生じた場合に別途検討 |
| O8 | **国際化（i18n）対応** | 日本語 UI 前提。別計画 |
| O9 | **Playwright UI テストの CI 組み込み** | Q3 回答: 手動実行でよい |
| O10 | **`routers/admin.py:90` の排他制御**（D12） | バックエンド。別修正 |
| O11 | **`routers/events.py:84` のキュー上限**（D13） | バックエンド。別修正 |

---

## 12. Resolved Questions（解決済み質問）

全 Q1-Q10 が計画者により回答済み。以下は回答サマリ：

| # | 質問 | 回答 | 反映先 |
|---|------|------|--------|
| Q1 | 機能タブのサブモジュール分割 | 許可（ベストプラクティスに基づく） | P6 追加 |
| Q2 | モバイル対応の目標 | 本格的対応 | P11 拡張 |
| Q3 | UI テストの CI 組み込み | 手動実行でよい | P14 から UI テスト除外 |
| Q4 | Playwright ベースライン画像管理 | git 管理継続 | O9 に反映 |
| Q5 | CSS リファクタリング | 正式フェーズとして追加 | P8 追加 |
| Q6 | `sections/chat.py` の Python 側分割 | 本格的に分割 | P7 追加 |
| Q7 | 優先フェーズ順序変更 | 特になし | 変更なし |
| Q8 | D6 エスケープ修正の優先度 | 別フェーズとして追加 | P4 追加 |
| Q9 | コンポーネント抽出の範囲拡大 | 機会駆動で追加 | P5 拡張 |
| Q10 | store.js のテストカバレッジ拡充 | テスト追加 | P2 に反映 |
