# MEMORY

## プロンプトキャッシュ共通化 (2026-07-24)
- `cache_utils.py` 新規作成: `split_system_prompt()`, `build_anthropic_system()`, `build_openai_system_messages()`
- `anthropic.py` のインライン `<!-- __STATIC_END__ -->` パース処理を `build_anthropic_system()` に委譲 (-11行)
- `openai_compat.py` の system message 構築を `build_openai_system_messages()` に委譲
- OpenAI/OpenRouter でも `cache_control: {"type": "ephemeral"}` が使えるようになった
- 教訓: 両プロバイダで同じロジックがコピペされていた。3つ目のプロバイダが来る前に共通化できてよかった。

## Portrait Feature Removal (2026-07-18)
- **削除ファイル**: Python 6件、JS/CSS 4件、テスト 3件 = 13ファイル
- **部分削除ファイル**: 25ファイル（Python backend, JS frontend, HTML sections, docs）
- 教訓: feature removalではgrep後に動的参照・未使用定数・CSSスタイルの見落としが発生しやすい。定義と参照の両軸で確認すること。

## Sudachi Dict Runtime Download (2026-07-18)
- `sudachidict_core` (~208MB) をランタイムダウンロードに切り替え、イメージサイズ 982→774MB (-21%)

## Toast / SSE Timing 教訓 (2026-07-20)
- **JSのsetTimeoutとCSSアニメーションの競合**: `animationend` イベント（`{ once: true }`）を使う方がCSSと正確に同期する。
- **チャットストリーミングのrAFバッチ**: 高頻度text_deltaのDOM書き込みは `requestAnimationFrame` でバッチ化。
- **自動スクロールの意図検出**: スクロール位置監視の閾値は80px。

## ディレクトリ構造リファクタリング (2026-07-20)
- `data/memory/{persona}/` → `data/persona/{persona}/`。Docker内データルート `/opt/nous` → `/data`。
- **Oracleレビュー必須**: 設定エイリアス（`data_dir`→`persona_dir`）はgrepでの参照漏れ検出が不可能。Oracleが6ファイルの致命的見落としを発見。
- **データ移行の安全手順**: (1)サーバ停止、(2)ファイル移動、(3)サーバ起動。`ensure_directories()` が起動時空ディレクトリを作るため逆順不可。

## コードリファクタリング (2026-07-20) — 合計約-415行削減

### Repository基底クラス抽出
- 5つの `SQLite*Repository` の `__init__`+`_db` パターンを `SQLiteRepository` 基底クラスに集約。
- 教訓: 同一シグネチャの `__init__` が3つ以上あれば基底クラス抽出を検討せよ。

### ドメインロジック重複統合
- `body_decay.py` と `emotion_decay.py` の指数関数的減衰計算を `compute_exponential_decay()` に統合。
- 教訓: コピペと思ったら迷わず共通化。

### MCPツールエラー形式の表記揺れ
- `_tools_memory.py` だけ `json.dumps({"ok": False, ...})`、他3ファイルは `{"success": False, ...}`。
- 教訓: 初期実装時に統一規約を作るべき。後修正はテストアサーション変更を伴う。

### テストフィクスチャ集約
- 14ファイルで同一フィクスチャ再定義 → conftest.py 1箇所に集約 (-109行)。

### 過剰try/exceptの除去
- `memory_repo.py` の参照系から try/except 除去 (27→8個, -85行)。

### Result伝播パターンは許容
- `if not result.is_ok: return Failure(result.error)` はRustの `?` 相当。抽象化すると可読性を損なうので許容。

## 内臓スキル5種 自律動作テスト (2026-07-22)
- **最終モデル**: `nvidia/nemotron-3-ultra-550b-a55b:free`（55B active, 1M context）
- `tencent/hy3:free` と `qwen/qwen3-coder:free` は無料期間終了で404。
- **結果**: 全5スキルが invoke_skill → 対象ツールのチェーンを達成（5/5合格）。

### 教訓
1. **OpenRouterの無料モデルは永続的でない**: ライブ確認が必須。テスト直前に存在確認すること。
2. **temperature=0 が小規模モデルのツール呼出に必須**: 決定論的動作でツール選択の一貫性が向上。
3. **プロンプトの命令形強化が効果的**: 「ツールを呼べ」「説明だけで済ませるな」の明示でモデルの行動が変わる。
4. **テスト間のセッションID一意性**: 同一session_idでコンテキスト汚染が発生。毎回UUIDで分離すること。
5. **Nemotron 3 Ultra はツール呼出に優秀**: 55B activeでも自律的スキル呼出を安定達成。レート制限（32 workers）に注意。

### 変更ファイル
- `data/persona/herta/config.json`: provider→openrouter, model→nemotron, temperature→0.0, enabled_skills修正
- `nous/application/chat/pipeline/prompt.py`: TOOL_USAGE_GUIDELINES強化、スキルヘッダー/末尾リマインダー改善
- `scripts/skill_test.py`: テストスクリプト新規作成

## クロススキル連鎖の汎用化 (2026-07-22)
- **方針**: 特定の組み合わせ（mood-sync→image-gen）だけでなく、全ツール呼出時に他ツール連鎖をチェックする汎用マトリクス。
- prompt.py `<cross_skill>` に全ツール間連鎖定義: memory_create↔memory_search, update_context→image_generate, goal_manage→memory_create, image_generate→memory_create。
- スキルdescriptionにも相互連鎖ヒントを追記（各SKILL.md）。
- 教訓: **最初から汎用設計せよ**。特定ペアの最適化より、全ツールの関係マトリクスの方が拡張性・一貫性で優る。
- 画像生成の予告禁止（「黙って呼べ」）はクロススキル全体で統一ルールに。

## Nous 類似プロジェクト調査 (2026-07-22)
- **結論**: 「MCPサーバー + ペルソナエンジン + WebUIチャット」の三点セットを持つのは Nous だけ。カテゴリの競合は実質不在。
- **直近OSS競合**: Woven Imprint（3層メモリ+5次元感情, MCP非対応）、Being（MCP+SOUL, クラウド依存）、Grimoire（MCP 15tools+Soul Systems, CLI中心）
- **Nousの独自優位性**: 二段階スキルシステム、ペルソナ完全分離、Ebbinghaus忘却曲線、Reflection/Mental Model、感情駆動Dynamic Temperature、日本語LLM最適化
- **競合が持つNous欠如機能（優先度順）**: マルチチャンネル（重大）、モバイルアプリ（重大）、グループチャット、ノーコードエディタ、自律スケジュール、MCP Apps対応
- **記憶システム競合**: Mem0（⭐61K, 最大コミュニティ）、Letta（MemGPT継承, 3階層メモリ）、Zep（時系列推論最強, LongMemEval 63.8%）
- **戦略的示唆**: マルチチャンネル統合が最大の機会的ギャップ。メモリのベンチマーク評価公開でMem0/Lettaに対抗可能。
- 詳細は`.spec/SPEC.md`内の調査レポート参照。

## プロンプト設計の層分離原則 (2026-07-22)
- **Oracleレビュー指摘**: システムプロンプトのTOOL_USAGE_GUIDELINESに具象ツール名と連鎖マトリクスをハードコードするのはアンチパターン。
- **設計原則**: システムプロンプト = 行動指針 + スキル発見（name+descriptionのみ）/ スキル内容 = 具体ツール名・連鎖指示 / API tools = 型情報。
- **効果**: プロンプトサイズ ~680→~300文字（-56%）。ツール追加時のプロンプト変更不要。
- **結論**: 小規模モデルは「長大な前提条件」より「invoke_skill結果の今やるべき指示」に従う方が得意。

## ペルソナ非依存パイプライン設計 (2026-07-22)
- **問題**: `prepare.py` の `_GAP_INSTRUCTIONS` にペルソナ固有の感情反応（「拗ねてた」「寂しかった」等）をハードコードしていた。
- **正しい設計**: パイプライン層は事実のみを伝達（「数日の空白がある」）。感情的反応はペルソナの性格定義と mood-sync に委ねる。
- **教訓**: 共有コードにペルソナ固有の口調・感情を埋め込むな。事実通知と表現は層を分離せよ。

## 時間経過検知 5段階自律チェーン検証 (2026-07-22)
- **結果**: Nemotron Super 120Bで TIME_CONTEXT(5日経過)→mood-sync→update_context(sadness)→image-gen→image_generate→memory_create の全段階が1ターンで完遂。
- **DB設計の注意点**: `_resolve_last_conversation_time()` は memories テーブルの最新タイムスタンプを最優先。context_state の値は memories が存在しない場合のみ参照される。テスト時は memories をクリア＋古いエントリ挿入が必要。
- **発見**: ツール呼出（ツールチェーン）とテキスト応答の一貫性が小規模モデルでは保証されない。ツールレベルでは sadness 検出＋悲しげ画像生成が成功しても、テキストは汎用挨拶になる場合がある。モデル品質に依存する課題。
- **設計検証完了項目**: ペルソナ非依存パイプライン、mood-sync時間トリガー、クロススキル連鎖、画像生成レート制限、relationship_decay、全部正常動作。

## テストモデル: openrouter/free (2026-07-22)
- **方針**: 特定モデル固定ではなく `openrouter/free` で自動ルーティング。OpenRouterのAuto Exactoがツール呼出成功率で最適プロバイダを選択する。
- **理由**: 無料モデルは予告なく終了する（hy3:free, qwen3-coder:free が404になった実績あり）。rate limit回避にも自動ルーティングが有効。
- **設定**: `data/persona/{persona}/config.json` の `model` を `"openrouter/free"` に（.gitignore対象のためローカルのみ）。
- **補足**: 特定モデルの動作検証が必要な場合は一時的に明示指定する。普段は自動ルーティング。
