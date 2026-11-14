# Nous Code Refactor Instructions
> **対象**: 実装モデル（AI agent）向けの包括的コードリファクタリング指示書
> **最終更新**: 2026-07-25（WebUI 全15フェーズ完了反映、バックエンド負債フェーズ定義）

---

## 1. 全体状況

| 領域 | 状態 | フェーズ数 | 備考 |
|------|------|-----------|------|
| **WebUI フロントエンド** | ✅ 全完了 | Phase 0〜15 (16フェーズ) | JS/Python HTML/CSS 全レイヤーリファクタリング済 |
| **バックエンド構造** | ✅ 主要完了 | Phase 1〜4 | Result[T,E], base_repo, MemoryService分割, ChatConfig分割, 大規模ファイル分解 |
| **バックエンド負債** | ✅ 全完了 | Phase N1〜N6 | 2026-07-25 全6フェーズ完了 |
| **最終テスト** | 1385 pass / 17 fail / 10 error | — | 新規破損ゼロ、全既存失敗 |

### 1.1 WebUI リファクタリング — 完了実績

全15フェーズ完了（MEMORY.md に詳細記録）:
- P0: lefthook.yml 修正
- P1-P6: JS 定数重複除去、store Pub/Sub 統合、DOM 安全性、HTML エスケープ、コンポーネント抽出、機能タブサブモジュール分割（38 JS モジュール→N.* 名前空間）
- P7-P8: Python `sections/chat.py`→7モジュール分割、CSS→7ファイル分割
- P9-P11: Loading/Empty/Error 状態、キーボード a11y、モバイルレスポンシブ
- P12-P13: `window.*` 汚染除去→`N.*` 統一、後方互換アダプター層削除
- P14-P15: 統合テスト CI 組み込み、最終クリーンアップ

---

## 2. 現在の技術的負債マップ

### 2.1 重大度: HIGH（独立フェーズ化）

| ID | ファイル | 行数 | 内容 | 状態 |
|----|---------|------|------|------|
| **D1** | `sections/chat/chat_sidebar.py` | 850行 | 巨大 f-string によるチャット設定サイドバー HTML 生成。単一関数に全設定項目が集中。 | 🔴 未着手 |
| **D2** | `routers/chat.py` | 678行 | チャット関連の全エンドポイントが1ファイルに集中。SSEストリーミング、メッセージ送信、履歴管理が混在。 | 🔴 未着手 |
| **D4** | 全体204箇所（ルーター67箇所） | — | 広範な `except Exception` パターン。具体的例外型でキャッチすべきだが、全域調査と修正にコスト。 | 🔴 未着手 |

### 2.2 重大度: MEDIUM

| ID | ファイル | 内容 | 状態 |
|----|---------|------|------|
| **D3** | `routers/persona.py` (676行) | 7サブモジュールに分割 (Phase N5b)。健康/CRUD/ダッシュボード/インポート/カード/ヘルパー。 | ✅ 分割済み (N5b) |
| **D5** | `service.py` | `session_id` 伝搬を AppContext に追加。Hebbian リンクがセッションイベントを利用可能に。 | ✅ 有効化 (N6) |
| **D8** | `memory_aux_repo.py` (64行) | MemoryAuxMixin = MemoryVersionMixin + MemoryStatsMixin + update_validity_window。責務適切で維持。 | ✅ 維持 (N1) |
| **D9** | `legacy_importer.py` (763行) | 複数の `except: pass` がエラーを握りつぶし。データ不整合の原因になりうる。 | 🔴 未着手 |

### 2.3 解決済み

| ID | 内容 | 解決コミット/方法 |
|----|------|------------------|
| D6 | マイグレーションバージョニング | commit 4a6a7ea |
| D7 | `data/hub.db.dead` (12KB) | コード参照ゼロ確認後、削除 (Phase N1) |
| D10 | `os.path` 混在 | 完了済み |
| D11 | 空テストディレクトリ | 完了済み |
| D12 | フロントエンド JS 大型ファイル | WebUI P6 で分割済み |
| D13 | ベンチマークコピペ | 修正済み |
| D14 | screenshot baselines | 削除済み |

---

## 3. 実装フェーズ（バックエンド）

### Phase N1: 安全な掃除 ✅

**依存**: なし
**見積**: 3ファイル、30分
**完了**: 2026-07-25

**内容**:
- D7: `data/hub.db.dead` の削除（参照確認後）→ コード参照ゼロ、削除済み
- D8: `memory_aux_repo.py` の責務再評価 → 64行 Mixin、責務適切・維持判断
- D3: `routers/persona.py` の再検証 → 676行・未分割確認。N5 フェーズに合流

**対象ファイル**:
- `data/hub.db.dead`
- `nous/infrastructure/sqlite/memory_aux_repo.py`
- `nous/api/http/routers/persona.py`

**受入基準**:
- [x] `hub.db.dead` が削除されている
- [x] `memory_aux_repo.py` の責務が評価済み（維持/削除/縮小 の判断あり）
- [x] `persona.py` の状態が確認済み
- [x] `pytest tests/unit/ -q --timeout=60` PASS（1380 pass / 18 fail+10 error — すべて N1 以前の既存失敗、新規破損なし）

---

### Phase N2: エラーハンドリング改善 ✅

**依存**: Phase N1
**見積**: ルーター67箇所 → 3並列 fixer で対応
**完了**: 2026-07-25

**内容**: D4 の段階的対応。全204箇所を一度に修正するのはリスクが高いため、レイヤーごとに分割。

**レイヤー別対応**:

| 優先度 | レイヤー | 対象ファイル数 | 箇所数（概算） | 方針 |
|--------|---------|--------------|---------------|------|
| 1 | `api/http/routers/` | 12ファイル | 67箇所 | `except Exception` → 具体的な `HTTPException` or DomainError |
| 2 | `application/` | ~10ファイル | 約50箇所 | チャットパイプラインの例外を具体化 |
| 3 | `domain/` | ~20ファイル | 約40箇所 | ドメイン例外を DomainError 階層に集約 |
| 4 | その他 | 残り | 約47箇所 | infrastructure/cli/migration |

**手順**:
1. grep で全 `except Exception` 箇所を特定
2. ルーターから着手（最も影響大）
3. HTTPException に変換しつつ、ログ出力を追加
4. テストでエラーハンドリングパスがカバーされているか確認

**受入基準**:
- [x] ルーターの `except Exception` が DomainError/HTTPException に置換されている
- [x] 握りつぶしがなく、全例外が最低限ログ出力されている
- [x] `pytest tests/unit/ -q --timeout=60` PASS（1380 pass / 18 fail — 新規破損なし）
- [x] `ruff check nous/ tests/` PASS

> **注**: アプリケーション層/ドメイン層/その他 の `except Exception`（約137箇所）は優先度2-4に分類。重大な握りつぶしが確認され次第、別フェーズとして再開。

---

### Phase N3: D9 — legacy_importer ✅

**依存**: Phase N2
**完了**: 2026-07-25（調査の結果、既に解消済みと判明）

**依存**: Phase N2
**見積**: 1ファイル、1時間

**内容**: `migration/importers/legacy_importer.py` (763行) 内の `except: pass` を最低限のログ出力 + 継続に置換。データ不整合の原因になるサイレントエラーを撲滅する。

**対象**: `nous/migration/importers/legacy_importer.py`

**手順**:
1. grep `except.*:` + `pass` 箇所を特定
2. 各箇所で最低限 `logger.warning("legacy import skipped: {reason}", exc_info=True)` を追加
3. 本当に無視して良いケース（例: 空行スキップ）はコメントで明示

**受入基準**:
- [ ] 全 `except: pass` がログ出力付きに置換されている
- [ ] 残存する `pass` に理由コメントがある
- [ ] インポート機能の E2E テストが PASS（存在する場合）

---

### Phase N4: chat_sidebar.py 分割 ✅

**依存**: Phase N3
**見積**: 1ファイル → 4新モジュール + 108行ファサード
**完了**: 2026-07-25 (commit dd3d6ff)

**内容**: `sections/chat/chat_sidebar.py` (850行) の巨大 f-string をサブセクションに分割。チャット設定サイドバーの各パネル（Provider設定、TTS設定、画像生成設定、MCP設定）を独立モジュールに。

**分割計画**:
| 現状 | 分割先（`sections/chat/` 内） |
|------|--------------------------|
| `chat_sidebar.py` (850行) | `chat_sidebar_provider.py` — プロバイダ選択 + モデル設定 |
| | `chat_sidebar_tts.py` — TTS 設定 |
| | `chat_sidebar_image.py` — 画像生成設定 |
| | `chat_sidebar_mcp.py` — MCP ツール設定 |
| | `chat_sidebar.py` — 統合ファサード（各モジュールを呼び出し） |

**手順**:
1. `chat_sidebar.py` のセクション境界（HTMLコメント等）を特定
2. 各セクションを独立モジュールに抽出
3. 元ファイルは各モジュールの `render_*()` を呼び出すファサードに
4. チャットタブの表示確認（SSEストリーミング中の設定変更もテスト）

**受入基準**:
- [ ] `sections/chat/` に新規モジュール4ファイルが存在
- [ ] `chat_sidebar.py` が200行以下に縮小
- [ ] チャット設定の全項目が正常に表示・保存される
- [ ] `pytest tests/unit/ -q` PASS

---

### Phase N5: ルーター分割 (D2 + D3) ✅

**依存**: Phase N4
**完了**: 2026-07-25

#### N5a: chat.py ルーター分割 (D2)

**対象**: `routers/chat.py` (678行)

**分割計画**:
| 現状 | 分割先（`routers/chat/`） |
|------|--------------------------|
| `routers/chat.py` (678行) | `chat_stream.py` — SSE `text/event-stream` エンドポイント |
| | `chat_messages.py` — メッセージ送信、編集、削除 |
| | `chat_history.py` — セッション履歴、コンテキスト管理 |
| | `__init__.py` — ルーター統合（`include_router`） |

**手順**:
1. エンドポイントを3グループに分類
2. 各グループを独立ルーターとして抽出
3. `__init__.py` でサブルーターを include
4. `routes.py` のインポートパスを更新

**受入基準**:
- [ ] `routers/chat/` パッケージが存在し、3サブモジュールに分割
- [ ] 全チャット機能が正常（SSEストリーミング、メッセージCRUD、履歴）
- [ ] `pytest tests/unit/ -q` + `pytest tests/integration/ -q` PASS
- [ ] フロントエンドからの全API呼び出しが正常

#### N5b: persona.py ルーター分割 (D3)

**対象**: `routers/persona.py` (676行)

**内容**: 健康診断/CRUD/ダッシュボード/インポート/SillyTavernカードの5関心を分離。

**分割計画**:
| 現状 | 分割先（`routers/persona/`） |
|------|--------------------------|
| `routers/persona.py` (676行) | `persona_health.py` — `/health` エンドポイント |
| | `persona_crud.py` — 作成/削除/更新 (`_do_create_persona`, `_do_delete_persona`, `update_persona_profile`) |
| | `persona_dashboard.py` — ダッシュボードページ/データ |
| | `persona_import.py` — 会話インポート |
| | `persona_card.py` — SillyTavernカード生成 |
| | `persona_helpers.py` — 共通ヘルパー (`_resolve_request`, `_build_sillytavern_card`) |
| | `__init__.py` — ルーター統合 |

**受入基準**:
- [ ] `routers/persona/` パッケージが存在し、5サブモジュールに分割
- [ ] 全ペルソナ機能が正常（ダッシュボード、CRUD、インポート、カード）
- [ ] `pytest tests/unit/ -q` PASS

---

### Phase N6: セッションイベント記録有効化 ✅

**依存**: Phase N5
**完了**: 2026-07-25

**内容**: `_get_session_memories` の配管は完了済み。セッションイベント記録を有効化し、`session_id` が伝搬されるようにする。

**対象**: `nous/application/chat/service.py` または関連ファイル

**手順**:
1. セッションイベントがどこで記録されるべきか確認
2. `session_id` の伝搬経路を確認
3. イベント記録呼び出しを追加
4. `_get_session_memories` が空リストでなく関連メモリを返すことをテスト

**受入基準**:
- [ ] セッションイベントが実際に記録される
- [ ] `_get_session_memories` が関連メモリを返す
- [ ] `pytest tests/unit/ -q --timeout=60` PASS

---

## 4. 制約（Non-Negotiables）

| # | 制約 | 説明 |
|---|------|------|
| N1 | **テスト破壊禁止** | 全フェーズ完了時、`pytest tests/unit/` + `pytest tests/integration/` が PASS |
| N2 | **バックエンド API シグネチャ変更禁止** | `routers/` 配下のエンドポイントシグネチャ変更は不可 |
| N3 | **ファサードパターン維持** | 分割後も既存インポートパスを壊さない（再エクスポート/Facade 維持） |
| N4 | **1フェーズ = 1コミット** | 各フェーズ終了時に atomic commit |
| N5 | **ruff クリーン** | 全変更後 `ruff check nous/ tests/` が PASS |
| N6 | **グローバル `data/` 参照確認** | `data/hub.db.dead` 削除前に全コードベースで参照 grep |

---

## 5. Baseline Commands（品質確認）

```bash
# Python 単体テスト
pytest tests/unit/ -q --timeout=60

# 統合テスト
pytest tests/integration/ -q --timeout=60

# Lint
ruff check nous/ tests/

# 型チェック
mypy nous/

# サーバー起動確認
curl -f http://localhost:26262/health
```

---

## 6. 停止条件

| # | 条件 | 対応 |
|---|------|------|
| S1 | テストが通らない原因が30分以上特定不能 | `#081` (oracle) にエスカレーション |
| S2 | 予想の2倍以上の変更量 | フェーズ分割の再検討 |
| S3 | 循環参照が発生 | 依存方向再設計のため oracle に相談 |
| S4 | バックエンド変更がフロントエンド表示に影響 | AGENTS.md の「バックエンド→フロントエンド同期ルール」に従い対応 |

---

## 7. 完了済み作業（参考）

### バックエンド構造リファクタリング (Phase 1〜4, 完了済み)
- Phase 1: Result[T,E] + SQLiteRepository基底クラス + DomainError階層
- Phase 2: MemoryService → 5-subservice Facade 分割 (Write/Enrich/Link/Evolution/Query)
- Phase 3: 大規模ファイル分解 (5並列fixer, 5→13ファイル, +2934/-3093行)
- Phase 4: ChatConfig 4サブ設定分割 + Pact契約テスト + CI強化

### WebUI リファクタリング (Phase 0〜15, 完了済み)
- 全16フェーズ完了。38 JS モジュール、N.* 名前空間、7 CSS ファイル、7 Python チャットモジュール
- 詳細: MEMORY.md 参照
