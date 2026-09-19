# nous 設計監査レポート — 2026-09-19

**目的**: nous プロジェクト全体（記憶設計・API・運用ルール・ペルソナ記憶連携）を、認知科学的な理想と実用性の両軸で監査し、「不足」「冗長」を重大度順に列挙する。
**性格**: 設計レベルの分析のみ。コード修正は含まない。
**スコープ外**: `docs/reviews/2026-09-19-full-feature-review.md` で処理済みのコード品質指摘（死にコード・層違反・巨大ファイル・パラメータ注記）。設計監査側はコード品質の問題を設計根拠として参照していない（引用する file:line は設計上の重複・欠落の位置特定のみ）。

## 方法

3 系統の並列調査 + 監査主体による検証。**検証深度の非対称（必読）**: 本レポートの指摘は 3 体の調査エージェントの file:line つき報告に基づく。うち **10 件（C1, C2, M5, M1, H3, H4, H5, H7, C4, M6）を監査本体がコードで実在確認**済み（付録 A）。**残りは二次報告に依存** — 行番号は調査時点のもので、個別実装前に当該行の再確認を推奨。出典のうち知識ベース由来の 4 項目（Tulving 1972, fuzzy-trace, weapon focus, FSRS arXiv ID）は一次未確認として付録 B に明示分離した。

| 系統 | 担当 | 産出 |
|------|------|------|
| 実装インベントリ | #009 | 記憶ライフサイクル全体の機構表（file:line つき）・冗長/不足候補 13 件 |
| 認知科学比較 | #042 | 人間記憶 8 機構との比較 + 主要 6 システム横断比較（出典約 30 件、一次文献確認） |
| 実用性監査 | #003 | MCP/スキル/ペルソナ連携/設定/WebUI 二重経路の指摘 34 件 |
| 検証 | 本体 | 最重要指摘 10 件（C1・C2・M5・M1・H3・H4・H5・H7・C4・M6）の実在性をコードで確認 |

凡例: 各項目の【 】は 分類（不足/冗長）と評価軸。検証済み ✅ = 監査本体が実在を確認。file:line は調査時点の HEAD。

---

## 0. エグゼクティブサマリ

監査全体を貫く 3 つの主病巣:

1. **契約の崩壊**（実用性最大の問題）— 同じ記憶操作が MCP・チャット組込・HTTP の 3 面に手書きで二重三重定義され、スキーマ・エラー契約・重複検出既定値が既に乖離。スキル群が「存在しないパラメータ」を指示している。設計の不足よりも**整合性の喪失**が運用リスクの核心。
2. **「データモデルだけ先走り、機構が未実装」の放棄層** — `interference_count`（加算箇所ゼロ ✅）、`confidence`（静的のまま）、`kind=prospective`（自発想起なし）、`environment`（検索未活用）、`episodic_time`（時系列クエリなし）。スキーマには在るが振る舞いが無い。出典・確信度・干渉・先見的記憶という**認知科学で最も実用価値の高い領域が、まるごと置き場だけ存在する状態**。
3. **認知科学アナロジーの過剰適用** — 感情強度→永続 stability は「フラッシュバルブ記憶の確信度インフレ」の模倣で、事実管理としては有害（Talarico & Rubin 2003: vivid さと確信度は残るが正確性は劣化する）。「忘却曲線」の FSRS 適用も、学習項目の想起確率モデルを重要度減衰に転用する名称上の過剰適用。

逆に、**削除すべきでない強み**も明確（§5）: FSRS v6・Hebbian+PPR 動的リンク・SWS 相当ワーカーは主要 6 システム（Mem0/MemGPT/Graphiti/A-MEM/MemoryBank）に対し先行または唯一の実装。

---

## 1. 重大（Critical）

### C1【冗長・実用性】MCP / チャット組込 / HTTP の 3 面契約が手書きで乖離 ✅一部検証済
- **根拠**: 同名 8 ツールのスキーマが `nous/api/mcp/tools.py` と `nous/application/chat/tools/definitions.py:41-206` で二重手書き。既に乖離（組込に `kind`・`appearance`・`tags`/`memory_key` なし）。エラー契約は 3 系統（`{"success":false,...}` / 平文 `Error: ...` / `str(dict)`）で、成功判定は `nous/api/mcp/_tools_helpers.py:63-78` の `startswith("Error")` という文字列ヒューリスティック。HTTP 経路は `UpdateContextRequest` に body_state/context_note 等の欠落フィールドがある。
- **連鎖被害**: スキル群（auto-memory, project-manage, mood-sync）がこの組込面の**存在しないパラメータ・存在しない delete を指示**しており、「宣言外パラメータを渡せるモデルなら偶然動く」運用になっている。
- **提案**: **単一のツール定義から 3 面を生成する**（単一情報源化）。共通 envelope `{ok, data, error:{code,message}}`、required 宣言、`tools.py`⇔`definitions.py` のスキーマ一致テスト。後方互換のため旧形式は段階併存。この 1 件で本レポートの実用性指摘の約 9 割（C1, M6, M7, L3, L4 関連）が同時に片付く。

### C2【不足・実用性】item_add の位置引数ズレ — 現行バグ ✅検証済
- **根拠**: `nous/api/mcp/_tools_item.py:25` は `add_item(item_name, category, description, quantity, tags)`（位置引数）だが、実体 `nous/domain/equipment/service.py:28-39` は `(name, category, description, visual_desc, quantity, tags)`。**quantity が visual_desc に、tags が quantity に入る**。tags 指定時は SQLite bind 失敗、無指定時は `visual_desc="1"` が残り appearance が文字列 `"1"` に汚染（`service.py:133-148` `build_appearance` → TTS 演技 prefix `nous/api/http/routers/tts.py:91-92` まで波及）。テスト `tests/unit/test_mcp_items.py:75` が誤呼び出しを固定している。
- **加えて**: appearance 合成が 3 経路で非対称（MCP あり / 自動抽出 `nous/domain/memory/memory_extractor.py:710` なし / HTTP `item.py:92-96` なし）。
- **提案**: キーワード引数化 + appearance 再計算を Service 層に一元化 + 3 経路パリティテスト。**契約統一と独立のホットフィックスとして即時対応**。

### C3【冗長・実用性】get_context のトークン予算が実態と乖離
- **根拠**: `nous/api/mcp/tools.py:103`（~500-800 tokens 主張）に対し、実装は `nous/api/mcp/_tools_helpers.py:342`（~700-900）、ACTIVE COMMITMENTS 件数無制限（`:434-440`）、Insights/Patterns/Summaries 全文（`:476-505`）、PROJECT 5 件×400 字（`:507-520`）。定常で 2,000-2,500 tokens、goals 多数時 6,000-8,000 tokens（算術的評価）。**毎セッション先頭に固定課金されるコストの設計値が 3 倍以上のブレ**。
- **提案**: 節ごとに件数+文字数上限をコードで強制（合計上限例 2,500 字）。docstring を実測値に修正しテストで固定。**順序注意**: 先に実測トークンを計測し、削れる節を決めてから絞る（「軽くなったが記憶が戻らない」を避ける）。

### C4【不足・認知科学】出典・確信度の動的管理不在（source monitoring）
- **根拠**: `Memory.source_type`/`confidence` は `nous/domain/memory/entities.py:39-40` に存在するが、confidence は作成時（既定 1.0）で**以後更新されない**。矛盾検出時の下降なし、複数出典の確証（corroboration）による上昇なし。`RecallAnnotator`（`nous/domain/memory/recall_annotator.py:43-64`）が confidence を表示に使うだけで、記憶の権威は実質「全記憶同格・確信度 1.0」。
- **認知科学的根拠**: source monitoring（Johnson et al. 1993）の欠如は「どこで聞いたか・観測か推論か」の区別不能 → LLM 幻覚・誤確信のトレーサビリゼロ。Graphiti は episode↔fact 双方向 provenance で実装済み（arXiv:2501.13956）— **主要 6 システム中 nous はここで最も遅れる**。
- **提案**: provenance（エピソード参照・source 種別・modality: 観測/推論/LLM要約/reflection）を全記憶に付与。confidence は「記憶の強度」と独立フィールドとし、矛盾解決時に下降・corroboration で上昇。**注意**: LLM 自己確信度は校正が弱いため検索重みに直結させない。
- **提案例（現実解）**: まず矛盾処理時に「旧記憶 confidence を下降させる」1 箇所だけ配線すれば、確信度フィールドが死んでいない状態になる。

---

## 2. 高（High）

### H1【不足・認知科学】エピソード→意味記憶の抽象化（スキーマ層）が未実装
- **根拠**: ConsolidationWorker（`nous/application/workers/consolidation_worker.py:196-210` `_build_gist`）は gist 生成と称しつつ実態は**見出し+content_preview の連結**（extractive concatenation）。CraniMem/CLS を名乗るが概念の抽出・統合・一般化はゼロ。エピソード→ノート（HiMem 2-tier）まではあるが、**ノート群の上に立つ抽象層（スキーマ/コミュニティ）が無い**。
- **認知科学的根拠**: 相補的学習系（McClelland et al. 1995）では海馬→新皮質の統合の産物は「一般化された意味記憶」。スキーマがあると新情報の統合が速くなる（Tse et al. 2007, Science）。Graphiti の community subgraph が実装済みの最良例。
- **提案**: オフライン統合の成果物として「LLM による統合・一般化された要約」を新規生成（連結ではない）。**必須条件**: gist は人間の fuzzy-trace 同様に詳細を失うため、エピソードへの provenance を保持（§C4 と接続）。
- **実用性の裏付け**: 「人間の睡眠の価値は情報喪失ではなく再構成」— 現行ワーカーは減衰・削除側に偏り、生成側（統合）が骨格止まり。実装価値: 高。

### H2【冗長・実用性】書込 1 回で semantic search 最大 3 回 + 矛盾検出 2 経路並列
- **根拠**: 重複排除（`nous/domain/memory/write_service.py:48`, 閾値 0.75）→ 進化探索（`nous/domain/memory/evolution_service.py:72`, 0.80）→ 矛盾無効化（`nous/domain/memory/contradiction.py:128`, 0.85）が同一 create 呼び出しで逐次発火。さらに `_run_background_evolution`（`evolution_service.py:165-182`）が **LLM 分類経路（A）と vector 閾値経路（B）を TaskGroup で同時実行** — 同一記憶を両方が閉じうる（冪等ガード `valid_until is not None` で安全は保たれるが、A の LLM 呼出が無駄になる）。
- **提案**: 矛盾検出を LLM 分類（3-op）に一本化し、閾値経路（B）を削除。semantic search は 1 回の検索結果を 3 段階で再利用（閾値違いはフィルタリングで対応可能）。

### H3【冗長・実用性】HTTP 書込経路が副作用（キャッシュ無効化・イベント発火）を欠く ✅検証済
- **根拠**: MCP 経路（`nous/api/mcp/_tools_memory.py:60-96`）は `memory.created` publish → vector upsert + query cache 無効化（`nous/application/use_cases.py:316-323`, `nous/domain/search/engine.py:84`）。HTTP 経路（`nous/api/http/routers/memory.py:237-274`）は **publish なし・手動 vector upsert のみ**。→ WebUI で記憶を編集した直後、MCP 検索が TTL 30 秒（`engine.py:53`）の間古い結果を返す。重複検出の既定値も 2 経路で逆。
- **提案**: HTTP ハンドラを service 層に委譲し、副作用（イベント発火・キャッシュ無効化）を service 層で発火。MCP/HTTP パリティ契約テストを追加。
- **一般化**: これは H2 の「3 面乖離」（C1）の個別事例。根本は同じ。

### H4【冗長・実用性】UI に表示される死に設定ノブ 7 個
- **根拠**: `forgetting_trigger_threshold` / `forget_ratio` / `forget_strength`（`nous/config/session_config.py:254-256`）、`reflection_threshold` / `reflection_min_interval_hours`（`:37-40`、実発火は `nous/application/workers/decay_worker.py:244` の周期のみ）、`mental_model_min_samples`（`:47`、呼出側は既定値 3 を使用）、`memory_enrichment_auto_run/interval/model/prompt_template`（`nous/application/use_cases.py:171,450` は enabled のみ読む）— **どこからも読まれない**のに `nous/api/http/static/chat/settings/save.js:230-264` で UI に露出。操作者が「効く」と信じて回す。
- **提案**: 削除 or 配線。「UI に出るキーは必ずコードから読まれる」grep ベース回帰テスト（本件だけで 7 個検出できた）。設定全体（推定 ~140 フィールド）は basic/advanced/expert の 3 層化が望ましい。

### H5【冗長・認知科学】感情強度→永続 stability は「確信度インフレ」の模倣
- **根拠**: `boost_on_recall`（`nous/domain/memory/entities.py:177-191`）が想起時に stability ×1.5（感情 gain）、`emotion_peak` を恒久保持。加えて感情値が 3 経路で管理: PersonaState → create 時スナップショット（`entities.py:36`）→ 変化時の直近メモリ上書き伝播（`nous/domain/persona/service.py:285-316`）— スナップショットの原本性が「最後の感情変化時」で上書きされ不整合。
- **認知科学的批判**: (1) 人間の感情変調は**統合窓の強化**であって想起時倍率ではない。1.5 の倍率定数に認知科学の出源は存在しない。(2) **フラッシュバルブ記憶の教訓**（Talarico & Rubin 2003）: 感情的記憶は vivid さと確信度だけが残り正確性は劣化する — 感情強度で stability を上げると「感情的だが事実的に壊れやすい記憶」が高権威で長生きする。stale fact の温床。
- **提案**: 感情強度は**検索時の一時的 salience ブースト（ランキング信号）**に限定し、永続 stability への反映を止める。`emotion_peak` 恒久保持を廃止。事実レポジトリとペルソナレイヤーで感情の用途を分離。
- **注**: 感情変調の**組み込み自体**は 6 システム中 nous 唯一で、ペルソナ対話という用途では価値がある。問題は適用先（stability 恒久化）。

### H6【冗長・実用性】RankPolicy 段で下流 4 段のスコア調整が計算だけ無駄
- **根拠**: `nous/domain/search/engine.py:29-46` `_finalize` で rank_policy 指定時、entity boost（`engine.py:236-258`, +0.1）・reranker（`:261-281`）・spreading activation（`:283-297`）・`ForgettingCurveRanker` 等のスコア調整を破棄して recency+importance+relevance で再スコアリング。既定経路（RankPolicy あり）では 4 段の計算が最終結果に寄与しない。
- **提案**: RankPolicy 有効時は該当段をスキップする short-circuit、または全段を RankPolicy の因子として統合。いずれも「検索パイプラインの段構成を構成可能にする」単一の設計判断で解消。

### H7【冗長・実用性】運用ルール（スキル群）が LLM に保持不可能な状態機械
- **根拠**: `session-start/SKILL.md:39-62` は初期 5 区分 × 再判定 4 経路 ×「cwd ごとに 1 回」の判定状態機械 — **判定済み cwd 集合を保持する仕組みが LLM には無い**。さらに保守者向けメタ注記（`:61`）が実行指示に混入。`make-project/SKILL.md` 手順 2 は既存タグ判定を「content のパス行の自然言語抽出」で行い、失敗モードが slug 分裂（タグ空間の永続汚染）。判定表が session-start と make-project で二重管理（必ずドリフトする）。同一ツールの上限が auto-memory（5 件/ターン）と project-manage（3 件/ターン）で競合。
- **提案**: (1) 判定表を 1 スキルに所有権集約、他方は参照のみ。(2) cwd 判定状態を外部化（セッション状態 or 専用ツール）。(3) プロジェクト判定を構造化タグ（`project_path:<abs>` 等）で行い自然言語パースを排除。(4) メタ注記を実行文から除去、過去事故のパッチ積層（否定形完了ゲート等）を 1 行の肯定形に集約。
- **実用性の本質**: この手順の複雑さは「LLM が守れないルールは書いても守られない」という運用原理に反する。分岐数は情報としての価値より違反リスクが上回る。

---

## 3. 中（Medium）

### M1【不足・認知科学】干渉（interference）がデータモデルだけ存在 ✅検証済
- **根拠**: `interference_count` は `nous/domain/memory/entities.py:95` 定義・`:162` ペナルティ適用・`strength_repo.py` 永続化の 3 箇所のみで、**加算箇所はコードベース全体でゼロ**。ペナルティ `−0.05×min(1, count/5)` は永遠に 0。
- **認知科学的論点**: RIF（Anderson et al. 1994）の**抑制実装そのものはエージェントに有害**（想起漏れ＝根拠欠落）。必要なのは抑制ではなく**競合解決** — 類似記憶ペア（類似度 0.8-0.9 のグレー帯）の定期レビューとマージ（パターン分離の応用、Yassa & Stark 2011）。
- **提案**: フィールドを活かすなら「新規作成時に類似 0.85-0.95 記憶へ interference_count+1」を最小実装し、閾値超過ペアを統合キューに流す。活かさないならフィールドごと削除（放棄層の解消）。

### M2【不足・認知科学】先見的記憶（prospective memory）の自発想起なし
- **根拠**: `kind="prospective"` は `VALID_KINDS` に存在するが、`valid_from` が未来の記憶は `nous/domain/search/engine.py:126-140` のフィルタで除外され、予定時刻前に surface する worker/仕組みなし。Goal/Promise も「置き場」であり、キュー条件（cue）と照合して能動注入する経路がない。
- **認知科学的論点**: PM 研究の核心は「記憶に保存するだけでは不十分、**トリガー条件の設計**が全て」（Einstein & McDaniel 1990）。ただし人間の PM は失敗が日常であり、エージェントではスケジューラで確実に再現すべき（人間の脆弱性の再現は不要）。
- **提案**: Goal/Promise に event-cue（エンティティ一致）/ time-cue（時刻）を付与し、get_context 生成時 or ワーカーで cue 照合 → 能動注入。実装コストは中、対話継続性への効用は高（「やるって言ってた」の再現）。

### M3【不足・認知科学】メタ記憶 — 「覚えていないこと」を自覚しない
- **根拠**: 検索空ヒット時、`log_search`（`nous/domain/memory/service.py:409`）は統計表示に使われるだけで、**「記憶が無い」ことを明示的に unknown として返す設計がない**。エンティティ/トピック別の記憶網羅度（カバレッジ）指標もなし。検索失敗からの学習ループが存在しない。
- **認知科学的論点**: メタ記憶（Nelson & Dunlosky 1991）— 特に delayed-JOL 効果「符号化直後の自己評価は不正確、遅延再評価で正確になる」は、importance 作成時固定（C4 と同根）の改善指針になる。FSRS の R(t) は既に各記憶の想起可能性の自己予測（事実上のメタ記憶）であり、**これを集計した「記憶健康度ダッシュボード」は全 6 システム未実装の空白地帯** — 差別化機会。
- **提案**: (a) 検索閾値以下時に「該当記憶なし（unknown）」を明示返却。(b) importance の遅延再評価パス（数日後）。(c) エンティティ別埋め込み密度のカバレッジ指標。実装コスト低。

### M4【不足・認知科学】時間的連続性（temporal contiguity）のクエリ機構なし
- **根拠**: `episodic_time`/`episodic_place`/`episodic_people` フィールド（`entities.py:28-30`）は保存されるが、「次に何が起きた？」の時系列列挙クエリがなく、Hebbian リンク（co-access ベース）は時間近接を考慮しない。`link_service.py:54-60` は episodic↔episodic を "temporal" と分類するが実際の時間で重み付けしない。
- **提案**: エピソード間の時間近接リンク形成（同日・同場所は初期重み加分）+ 「この記憶の前後」クエリ。ペルソナ対話では「あの時の話の流れ」の再現に直結。

### M5【冗長・実用性】重複検出が既定 OFF ののに、スキルは「自動除去される」と虚偽 ✅検証済
- **根拠**: `nous/api/mcp/tools.py:121` `skip_duplicate_check: bool = True`（既定で無効）。一方 `data/skills/auto-memory/SKILL.md:22` は「重複はサーバー側で自動除去される」と断言。→ 重複記憶が蓄積し、skill の前提が虚偽。
- **提案**: 既定を False に統一（書込コスト増を許容するなら）か、このノブを LLM 面から撤去。スキル文言は実態に合わせる。**注**: 重複排除が有効でも 0.75 閾値の判定は write_service 内 — 設定の「既定値の意味」をドキュメント側が知らないのが本質。

### M6【冗長・実用性】ファジー（query 指定）破壊操作の閾値なし
- **根拠**: `nous/api/mcp/_tools_memory.py:309-315` — delete は semantic top-1 を**閾値なし**で削除。update の query 解決（`:219-224`）も同様。一方 `goal` は 0.3 閾値（`_tools_goal.py:154`）。方針がバラバラ。
- **提案**: query 削除は候補提示→確認の 2 段階、または key 必須化。解決閾値は単一定数に統一。

### M7【冗長・実用性】required 漏れ + サーバー内部較正ノブの漏出
- **根拠**: `tools.py:114,168,198-199,312` — 必須引数に既定値が付いてスキーマ required にならず、空呼び出し→実行時エラー→往復増。逆に `memory_search` の importance/recency 重み（`:208-230`）は LLM が較正不能な内部ノブ（`_tools_memory.py:17-21` に内部校正メモまで露出）。
- **提案**: 必須は `Field(min_length=1)` で required 化（テスト固定）。公開面は query/top_k/tags/kind/sort に絞り、重みは `profile="recent"|"deep"` 等のプリセットに畳む。

### M8【冗長・実用性】get_context の読取副作用 + 死に one-shot 経路
- **根拠**: get_context が `record_conversation_time` + one-shot 状態メモリ消費（`_tools_persona.py:118-130`）を行う。**内製コードが既にこの副作用を回避するコメントを書いている**（`curiosity.py:224`）= 危険が実証済み。one-shot の書込側は現存せず、毎回 2 クエリが空取り。
- **提案**: get_context を読取専用に。session_start 副作用は別ツール/明示パラメータへ。one-shot は削除。

### M9【冗長・実用性】装備システムの固定費が価値に対し過大
- **根拠**: 毎ターン item 抽出 LLM 1 回（`post.py:138` + `memory_extractor.py:428`）、未装着込み 8 行を毎ターン注入（`context_loader.py:325-335`）、専用 LLM 設定 5 件（`session_config.py:156-160`）、`auto_add` が幻アイテム生成（`equipment/service.py:141-149`）。取得価値は appearance と風味のみ。
- **提案**: 未装着行の注入停止、auto_add 明示化、item 抽出を inventory 変化時のみに。**装備システム自体はペルソナ対話の固有価値**（汎用記憶システムに無い差別化）だが、常時課金の構造を見直す。

### M10【冗長】recency 減衰の二重適用と係数不整合
- **根拠**: strength 計算で FSRS recall（時間減衰）× `compute_strength_score` の recency 因子（`entities.py:150`, exp(-age/7)）が独立に二重減衰。検索 ranking の recency（`shared/time_utils.py:12`, λ=0.5・半減期 1.4 日）と strength 側（λ≈0.1・7 日）で**係数が 3.5 倍乖離** — ad hoc 調整の痕跡。
- **提案**: 「時間」は FSRS recall に一元化し、score 内 recency 因子を削除。検索側係数は docs に根拠を明記（2026-09-15 の recency_weight 0.05 校正との整合も確認）。

---

## 4. 低（Low）

### L1【不足・認知科学】再統合型のバージョン付き書き換え
矛盾検出時の旧記憶処理が「無効化（tombstone）」のみ。想起された記憶が新情報で書き換わる reconsolidation（Nader et al. 2000）相当は、エージェントでは「勝手な書き換えは害」だが**矛盾解決時の旧→新バージョン移行**（Graphiti の edge invalidation 方式）は価値あり。`memory_version_mixin` が既にあるので実装下地は存在。

### L2【不足・認知科学】文脈依存想起 — environment フィールドの未活用
`PersonaState.environment`（`persona/entities.py:19`）は保存のみで検索に未使用。人間の符号化特定性（Godden & Baddeley 1975）は**効果の再現性自体に疑問**（RSOS 2020 再現失敗）であり、エージェントに身体的文脈はない。高コスパな適用のみ: 「現在のタスク文脈を検索クエリに足す」拡張。優先度低。

### L3【冗長・実用性】自動抽出の kind が常に semantic
`memory_extractor.py:435-470` — kind 未指定＝常に semantic。結果、全自動記憶が semantic になり kind フィルタとスキル記述が実質無効。抽出プロンプトに kind を入れるか、機能ごと削除。

### L4【冗長・実用性】能力マトリクス不揃い
unequip/update/remove は HTTP のみ、blocks/observations も HTTP のみ。外部エージェントは「帽子を脱げない」。能力表を docs に明記し、最低限 unequip を MCP 面へ。

### L5【冗長・実用性】表記・ドリフト系
"20+ tools" 表記 vs 実登録 12（`tools.py:89`）。`irodori_chunk_min_chars` が 3 箇所で異なる値（85/40/40getattr）。settings reset が収集対象外で静かに無効（`reset.js:182` vs `save.js:230`）。env と persona 設定の優先順位が場当たり（`tts.py:371-379`）。→ 単一定義化 + 優先順位表を docs に。

### L6【冗長・実用性】運用ルールの重複記載
memory_search 上限の競合（M7 と同根）、recall-weaver 3 クエリ必須の base_system との二重記載、`memory_search` タグ検索の内部実装に関する誤ったメンタルモデルを SKILL が教えている（`session-start/SKILL.md:87` vs 実装 `engine.py:164,399-407`）。→ 「タグ検索は query 空」のルール化のみにし内部説明を削除。

---

## 5. 削除対象にしない強み（監査での保持判断）

| 機構 | 6 システム比較での位置 | 判断根拠 |
|------|----------------------|---------|
| FSRS v6 忘却曲線 + importance 変調 | 最も精緻（MemoryBank は Ebbinghaus、他は曲線なし） | 主要システムに対する先行。名称の「忘却」過剰適用（§0-3）だけ表記改善 |
| Hebbian 共活性 + Oja 正規化 + PPR 拡散 | 動的リンク強化は唯一（Mem0/Graphiti は静的意味エッジ） | リッチゲットリッチは Oja+自発減衰で緩和済み。リンク重み上限・減衰率の定期監査を推奨 |
| SWS 相当オフラインワーカー | Letta sleep-time と双璧 | **生成側（統合）を H1 で補強するのが次の一手** — 削除ではなく成長方向 |
| archive 経由の削除（不可逆削除なし） | 全システム中最も安全な忘却設計 | 人間の「不可逆忘却は有害」という知見（Rasch & Born 2013 の downscaling は非可逆ではない）にも整合 |
| 感情変調の組み込み自体 | 6 システム中唯一 | ペルソナ対話の用途では価値。適用先（stability 恒久化）だけ修正（H5） |
| Goal/Promise ライフサイクル | 実装済みは少数派 | M2 で cue 機構を足せば差別化 |

**戦略機会**: メタ記憶ダッシュボード（M3）— FSRS R(t) の集計は既存データだけで実装可能で、主要 6 システムすべて未実装。差別化の最短経路。

---

## 6. 改善提案の統合ロードマップ（優先順）

| 優先 | アクション | 解消する項目 |
|------|-----------|------------|
| 1 | **ホットフィックス**: item_add キーワード引数化 + appearance 一元化（C2）。ファジー delete の閾値/確認 2 段階化（M6） | 現行バグ。契約作業と独立 |
| 2 | **契約の単一情報源化**: 単一ツール定義から MCP/組込/HTTP を生成、共通 envelope、スキーマ一致テスト（C1） | 実用性指摘の約 9 割の根本。後方互換に注意（旧形式段階併存） |
| 3 | **感情→stability の停止**、ランキングブーストへ移行、emotion 伝播の一本化（H5） | stale fact の温床遮断。ペルソナ価値は維持 |
| 4 | **放棄層の意思決定**: interference_count / confidence / prospective / environment / episodic_time を「最小実装するか削除するか」1 つずつ決定（C4, M1, M2, M4, L2） | 「データモデルだけ先走り」の解消。削除も正当な選択 |
| 5 | **get_context 予算強制**: 実測 → 上限コード化 → docstring 修正（C3） | 毎セッションの固定コスト設計値を回復 |
| 6 | **スキル判定表の縮約**: 所有権集約・判定状態外部化・構造化タグ dedupe（H7） | 運用違反（タグ汚染）の予防 |
| 7 | **SWS ワーカーの生成側強化**: LLM gist 統合 + provenance 保持（H1, C4 と接続） | 認知科学軸の最大の不足 |
| 8 | 死に設定ノブ削除 + UI キー回帰テスト（H4）、RankPolicy short-circuit（H6）、検索経路の一本化（H2, H3） | 冗長性の掃除 |

---

## 付録 A: 監査本体による実在性検証（4 件）

| 項目 | 検証内容 | 結果 |
|------|---------|------|
| C2 | `nous/api/mcp/_tools_item.py:25` の位置引数と `nous/domain/equipment/service.py:28-39` の署名突合 | ✅ 引数ズレ実在（quantity→visual_desc, tags→quantity） |
| M5 | `nous/api/mcp/tools.py:121` 既定値確認 | ✅ `skip_duplicate_check: bool = True` |
| M1 | `interference_count` の全出現箇所 grep | ✅ 加算箇所ゼロ（定義・スコア・永続化のみ） |
| H3 | `nous/api/http/routers/memory.py` の publish/event_bus 検索 | ✅ create_memory に publish なし |
| H5 | `boost_on_recall`（`nous/domain/memory/entities.py:177-191`）の実装内容 | ✅ `gain = min(1.0 + gain_k × emotion_intensity, 1.5)`・`emotion_peak` の恒久 max 更新を実在確認 |
| H4 | `forgetting_forget_ratio` などの死にノブ | ✅ 定義は `nous/domain/session_config.py:255` 周辺、コード上の読取経路なしを確認 |
| H7 | `session-start/SKILL.md:61` のメタ注記混入 | ✅ 「この復元指示は session-start 側にのみ書き…」の実行指示内混入を原文確認 |
| C4 | confidence の動的更新の不在 | ✅ `nous/domain/memory/service.py` での confidence 出現は既定 1.0 付与とパススルーのみ、更新ロジックなし |
| M6 | query 指定 delete の閾値なし | ✅ `nous/api/mcp/_tools_memory.py:305-318` で top-1 を閾値なしで削除 |
| C1 | エラー契約ヒューリスティック | ✅ `nous/api/mcp/_tools_helpers.py` に `startswith("Error")` 系の文字列判定実在 |

他の指摘（Critical/High/Medium/Low の残り）は担当エージェントの file:line つき報告に基づく二次情報である（行番号は調査時点）。個別対応時は該当行の再確認を推奨。

## 付録 B: 認知科学比較の主要出源（一次文献確認済み）

Rasch & Born 2013 (Physiol Rev) / Walker & Stickgold 2004 (Neuron) / Klinzing et al. 2019 (Nat Neurosci) / Nader, Schafe & LeDoux 2000 (Nature 406:722-726) / Anderson, Bjork & Bjork 1994 (JEP:LMC 20(5)) / Yassa & Stark 2011 (TINS 34(10):515-525) / Bjork & Bjork 1992 / McClelland, McNaughton & O'Reilly 1995 (Psychol Rev 102(3)) / Tse et al. 2007 (Science 316:76-82) / Johnson, Hashtroudi & Lindsay 1993 (Psychol Bull 114(1)) / Einstein & McDaniel 1990 (JEP:LMC 16(4)) / Godden & Baddeley 1975 (Br J Psychol 66(3)) + 再現失敗 (RSOS 2020) / Nelson & Dunlosky 1991 (Psychol Sci 2(4)) / McGaugh 2000 (Science 287) & 2004 (Annu Rev Neurosci 27) / Talarico & Rubin 2003 (Psychol Sci 14(5)) / Lisman & Grace 2005 (Neuron 46(5))。エージェント記憶システム: Mem0 (arXiv:2504.19413) / MemGPT (arXiv:2310.08560) + Letta sleep-time / Zep-Graphiti (arXiv:2501.13956) / A-MEM (arXiv:2502.12110) / MemoryBank (arXiv:2305.10250) / HiMem (arXiv:2601.06377)。

**未検証の知識ベース項目**（レポート採録時に注意）: Tulving 1972 区分、fuzzy-trace theory、weapon focus、FSRS の arXiv ID。
