# MemoryMCP ユーザー目線 包括的テスト計画 v1

> 2026-06-27 | 対象: WebUI全11タブ + MCPツール全24件 + 設定UX + Dockerセットアップ

---

## 1. WebUI 網羅テスト

### 1.1 Overview タブ

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| OV-01 | ダッシュボード表示 | `/dashboard/default` にアクセス | 全カードが正常描画。スケルトン→データ表示の遷移が1秒以内 | P0 |
| OV-02 | Profileカード | ペルソナ名/ニックネーム/関係性が表示される | `PUT /api/personas/default/profile` で変更後、再読込で反映 | P1 |
| OV-03 | Memory Stats (4値) | Total/Goals/Promises/Reflections の数値 | `POST /api/memories` で作成後、数値が+1される | P1 |
| OV-04 | Equipment管理 | 装備スロットにアイテム追加/解除 | equip→スロット表示反映、unequip→空に戻る | P1 |
| OV-05 | Inventory CRUD | アイテム追加・削除 | 追加→リスト追加、削除→リストから消える。confirm表示 | P2 |
| OV-06 | Body Sensations | Fatigue/Warmth/Arousal/Heart/Pain の5バー | `update_context` で変更後、5-10秒以内にバーが更新 | P2 |
| OV-07 | Core Memory Blocks | ブロック作成・編集・削除 | 新規作成→カード表示、削除confirm→消える | P2 |
| OV-08 | 7-Day Timelineグラフ | Chart.js棒グラフ | 過去7日分の日別メモリ数が正しく表示 | P2 |
| OV-09 | Tag Distribution円グラフ | Chart.jsドーナツ | 上位タグが色分け表示 | P3 |
| OV-10 | Goals & Promisesリスト | アクティブな目標/約束の一覧 | goal_manageで作成後、ページ再読込で反映 | P2 |
| OV-11 | Relationship Highlights | 関係性の高いエンティティ表示 | エンティティ関係がある場合に表示 | P3 |
| OV-12 | エラーハンドリング | Qdrant停止状態でアクセス | errorCard() が表示。APIエラー時にクラッシュしない | P1 |

### 1.2 Memories タブ

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| ME-01 | メモリ一覧表示 | Memoriesタブを開く | ページネーション付きで20件ずつ表示。件数/ページ数が正しい | P0 |
| ME-02 | 検索（キーワード） | 検索バーにキーワード入力→Enter | 関連メモリが表示される。結果件数が表示 | P0 |
| ME-03 | 検索（タグ） | タグ選択ドロップダウン | 選択タグにマッチするメモリのみ表示 | P1 |
| ME-04 | 新規メモリ作成 | New Memoryボタン→内容/重要度/感情/タグ入力→Save | 201 Created。一覧に追加。toast通知 | P0 |
| ME-05 | メモリ編集 | メモリのEdit→内容変更→Save | 200 OK。変更が反映。toast通知 | P1 |
| ME-06 | メモリ削除 | メモリのDelete→confirm | confirm表示→OKで削除。一覧から消える | P1 |
| ME-07 | バッチ削除 | 複数チェック→Batch Delete | 選択件数表示→confirm→全削除 | P2 |
| ME-08 | 詳細モーダル | メモリ行クリック | 全フィールド（Body State/Emotionバー含む）表示 | P2 |
| ME-09 | 表示切替 Card/Compact | Viewボタン切替 | カード表示↔コンパクト表示が即時切替 | P3 |
| ME-10 | ソート切替 | Newest/Oldest/Importance/Strength/Updated | 並び順が即時変更 | P1 |
| ME-11 | Advanced Search | 折りたたみパネル→各フィルター設定→Apply | 複合条件でフィルタリング | P2 |
| ME-12 | 検索モード切替 | semantic/keyword/hybrid/smart | 各モードで結果が異なる（semantic:ベクトル、keyword:全文検索） | P2 |
| ME-13 | ページネーション | ページ番号クリック/次へ/前へ | 正しいページに遷移。total_pages表示 | P1 |
| ME-14 | エラー時 | 無効なpersonaでアクセス | errorCard() + "Persona not found" | P2 |

### 1.3 Chat タブ

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| CH-01 | メッセージ送受信 | テキスト入力→Enter送信 | SSEストリーミングでアシスタント応答がリアルタイム表示 | P0 |
| CH-02 | Markdownレンダリング | `**太字**` `- リスト` ` ```コード``` ` を含む応答 | marked.js+DOMPurifyで正しくHTML変換 | P1 |
| CH-03 | コードハイライト | コードブロックを含む応答 | highlight.jsでシンタックスハイライト | P2 |
| CH-04 | Memory Panel（左） | チャット中にretrieved/savedメモリ表示 | SSEイベントでリアルタイム更新 | P1 |
| CH-05 | メモリ編集（吹き出し内） | アシスタント応答内のEditボタン | モーダルでメモリ編集→保存 | P2 |
| CH-06 | コマンド補完 | `/` 入力 | 10コマンドの候補がポップアップ表示 | P1 |
| CH-07 | 音声入力 | マイクボタンクリック | Web Speech APIが動作（ブラウザ依存） | P3 |
| CH-08 | 会話エクスポート | Exportボタン | HTMLファイルがダウンロードされる | P3 |
| CH-09 | Settingsパネル（右） | Provider/Model/API Key変更→Save | 設定が保存され次回会話に反映 | P0 |
| CH-10 | MCPサーバー設定 | JSONエディタでMCPサーバー追加 | MCPツールがチャットで利用可能に | P1 |
| CH-11 | Skills表示 | Settings→Skillsセクション | 利用可能スキル一覧が表示 | P2 |
| CH-12 | コンテキスト最適化 | Stored Msgs/Token Limit変更 | 設定値が保存され適用 | P2 |
| CH-13 | Housekeeping | Housekeepingボタン | `POST /api/chat/{persona}/housekeeping` → 成功toast | P3 |
| CH-14 | 中止ボタン | 応答生成中にStop | SSE接続が切断され入力可能に | P1 |
| CH-15 | SSE再接続 | ネットワーク切断→復帰 | 指数バックオフ(5s→60s)で自動再接続 | P2 |
| CH-16 | 複数会話セッション | セッションID指定で履歴復元 | `GET /api/chat/{persona}/sessions/{id}` で過去会話表示 | P3 |

### 1.4 Coding Agent（Chatタブ内フローティング）

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| CA-01 | Pythonコード実行 | Terminalに `print(1+1)` → Run | 出力 "2" + 終了コード 0 | P0 |
| CA-02 | Bashコード実行 | 言語切替→ `echo hello` → Run | 出力 "hello" + 終了コード 0 | P1 |
| CA-03 | ファイル一覧 | Filesタブ | サンドボックス内のファイル一覧がAPI経由で表示 | P2 |
| CA-04 | ファイルアップロード | ドロップゾーンにファイルドロップ | アップロード成功→ファイル一覧に追加 | P2 |
| CA-05 | ファイル削除 | ファイル名の横のDelete | confirm→削除成功→一覧から消える | P3 |
| CA-06 | 画像アーティファクト表示 | コード実行で画像生成 | 生成画像がimgタグで表示 | P2 |
| CA-07 | sandbox無効時 | sandbox.enabled=falseでCoding Agent使用 | 適切なエラーメッセージ表示、クラッシュしない | P2 |

### 1.5 Settings タブ

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| ST-01 | 全カテゴリカード表示 | Settingsタブを開く | server/embedding/reranker/qdrant/worker/general/search/persona/summarization/forgetting の10カテゴリ表示 | P0 |
| ST-02 | 設定値変更→Apply | 任意の設定値を変更→Apply | PUT /api/settings → 即時反映（hot_reload=True項目） | P0 |
| ST-03 | 設定値リセット | Resetボタン | デフォルト値に戻る | P1 |
| ST-04 | 設定プロファイル切替 | Development/Production | プリセット値が一括適用 | P1 |
| ST-05 | ユーザープロファイル保存 | 現在設定→Save Profile | localStorageに保存。次回復元可能 | P2 |
| ST-06 | 検索フィルター | 設定名で検索 | マッチする設定のみ表示 | P2 |
| ST-07 | 差分検出 | 値をデフォルトから変更 | 青ドット表示 | P3 |
| ST-08 | バリデーション | 数値範囲外/不正URL入力 | 赤枠+エラーメッセージ。Apply不可 | P1 |
| ST-09 | 依存ルール | summarization.use_llm=false→LLM項目グレーアウト | 関連項目が無効化 | P2 |
| ST-10 | 埋め込みモデルリロード | モデル名変更→Apply | 進捗バー→"ready"ステータス→dimension表示更新 | P2 |
| ST-11 | Export Config | Exportボタン | 全設定のJSONがダウンロード | P3 |
| ST-12 | Reset All to Defaults | Reset All→confirm | 全設定がデフォルトに戻る | P2 |
| ST-13 | 設定ステータスポーリング | embedding reload中 | 2秒間隔で `/api/settings/status` をポーリング、進捗表示 | P2 |

### 1.6 Analytics タブ

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| AN-01 | Emotion Timeline | 7d/30d/3M/1Y切替 | Chart.js折れ線グラフが日付範囲に応じて更新 | P1 |
| AN-02 | Memory Strength分布 | デフォルト表示 | 棒グラフ+統計値(Total/Avg/Weak/Strong) | P1 |
| AN-03 | データなし時 | 新規ペルソナでAnalytics表示 | 空状態メッセージ、クラッシュしない | P2 |

### 1.7 Timeline タブ

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| TL-01 | タイムライン表示 | メモリが時系列で表示 | vis-timelineに感情カラーでアイテム表示 | P1 |
| TL-02 | フィルター（感情/タグ/重要度≧） | 各フィルター設定 | フィルター条件でアイテム絞り込み | P2 |
| TL-03 | アイテムクリック→詳細 | アイテムクリック | スライドアウトパネルにBody State + Emotionバー表示 | P2 |
| TL-04 | 件数切替 50/100/200/500 | 件数変更 | 表示件数が変わる。API再取得 | P2 |

### 1.8 Knowledge Graph タブ

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| KG-01 | グラフ表示 | ノード・エッジが描画 | 感情色+重要度サイズのノード、実線/破線のエッジ | P1 |
| KG-02 | フィルター（タグ/感情） | フィルター変更 | ノード絞り込み | P2 |
| KG-03 | Physicsトグル | checkbox切替 | フォースシミュレーションON/OFF | P3 |
| KG-04 | ノードクリック→詳細 | ノードクリック | スライドアウトにメモリ内容/タグ/感情/重要度 | P2 |
| KG-05 | ノード数制限 50/100/200 | 制限変更 | API再取得。limit値がAPIに渡される | P2 |

### 1.9 Import/Export タブ

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| IE-01 | Conversation Import | ファイルパス入力→Import | `POST /api/import-conversation/{persona}` が成功 | P1 |
| IE-02 | ZIP Import（Drag & Drop） | ZIPファイルドロップ | 進捗バー→結果カード（imported件数） | P1 |
| IE-03 | Export（ZIP） | ZIP選択→Export | ZIPファイルがダウンロード | P1 |
| IE-04 | Export（JSON） | JSON選択→Export | JSONがダウンロード。または `GET /api/dashboard` 経由 | P2 |
| IE-05 | Export Preview | 現在の統計表示 | メモリ数/アイテム数/装備数 | P3 |
| IE-06 | 無効ファイル | 非ZIPファイルドロップ | 適切なエラーメッセージ | P2 |

### 1.10 Personas タブ

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| PE-01 | ペルソナ一覧 | 全ペルソナがカード表示 | 記憶数/最終会話/感情/BodyStats表示 | P0 |
| PE-02 | 新規ペルソナ作成 | New Persona→名前入力→Create | 201 Created。カード追加 | P1 |
| PE-03 | プロフィール編集 | Edit→UserName/Nickname/Address/Relationship変更→Save | PUT成功。toast通知 | P1 |
| PE-04 | ペルソナ切替 | Switchボタン | クライアント側persona変更。タブ再読込 | P1 |
| PE-05 | ペルソナ削除 | Delete→confirm | DELETE成功。カード削除。defaultは削除不可 | P1 |

### 1.11 Admin タブ

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| AD-01 | Rebuild Vector Store | Rebuild→confirm | 進捗バー→結果表示。Qdrant再構築成功 | P0 |
| AD-02 | Database Stats | 6項目表示 | 数値が正しい | P2 |
| AD-03 | System Info | Version/Status/Qdrant/Session Uptime/Persona | `/health` から取得した値が表示 | P2 |

### 1.12 Activity タブ

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| AC-01 | セッションイベント一覧 | 全イベント表示 | セッションカード（ID/Platform/件数/時間） | P1 |
| AC-02 | フィルター（Event Type） | タイプ選択 | Tool Calls/Chat Messages/LLM Responses等で絞込 | P2 |
| AC-03 | イベント詳細展開 | イベント行クリック | 折りたたみ展開でdetail表示 | P2 |
| AC-04 | Load More | ボタンクリック | offset更新→追加イベント読み込み | P2 |
| AC-05 | ソート切替 Newest/Oldest | 切替 | 並び順変更 | P3 |

### 1.13 Skills（スタンドアロン）

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| SK-01 | スキル一覧 | テーブル表示 | 登録済みスキルが一覧表示 | P1 |
| SK-02 | 新規スキル作成 | 名前/説明入力→Create | POST成功。テーブルに追加 | P2 |
| SK-03 | スキル編集 | 行内Edit→変更→Save | PUT成功 | P3 |
| SK-04 | スキル削除 | Delete | confirm→削除成功 | P3 |
| SK-05 | ファイルから同期 | Syncボタン | POST /api/skills/sync → ファイルシステムのスキルがDBに反映 | P2 |

### 1.14 横断テスト

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| CT-01 | タブ切替 | 全11タブを順に切替 | 各タブが正常ロード。前タブの状態が破壊されない | P0 |
| CT-02 | ペルソナ切替の影響 | persona切替→各タブ確認 | 全タブが新personaのデータに切り替わる | P1 |
| CT-03 | ブラウザリロード | 任意の状態でF5 | 元のタブが復元されるか、ダッシュボードに戻る | P1 |
| CT-04 | モバイル表示 | 320px幅で表示 | レイアウト崩れなし。各UI要素が操作可能 | P3 |
| CT-05 | SSE メモリ通知 | `memory_create` MCP→WebUIトースト | "New memory created" トーストが3.2秒表示 | P2 |
| CT-06 | パフォーマンス | 1000件メモリのMemoriesタブ | 表示が3秒以内。ページネーションが遅延しない | P3 |

---

## 2. MCPツール 網羅テスト

### 2.1 メモリ系（7ツール）

| # | ツール | テストシナリオ | 検証ポイント | 優先度 |
|---|--------|-------------|------------|:---:|
| MC-01 | **memory_create** | content="テスト", importance=0.8, tags=["test"], emotion="happy" | 201 Created。key返却。Qdrantベクトルupsert成功 | P0 |
| MC-02 | | content=""（空） | エラーにならず空メモリが作られるか、適切に拒否されるか | P2 |
| MC-03 | | importance=1.5（範囲外） | バリデーションでclamp（0.0-1.0）されるか、エラーになるか | P2 |
| MC-04 | | tags=["a"*200]（長すぎ） | バリデーションで拒否されるか（max 100 chars） | P3 |
| MC-05 | **memory_read** | key指定→単一取得 | メモリ全フィールドが返る。tombstoned除外 | P0 |
| MC-06 | | key省略→最新10件 | 直近10件が降順で返る | P0 |
| MC-07 | | limit=5, offset=5 | 6-10件目が返る | P1 |
| MC-08 | | 存在しないkey | 適切なエラーメッセージ | P2 |
| MC-09 | **memory_update** | content変更 | 更新成功。updated_at更新 | P0 |
| MC-10 | | emotion変更 | _VALID_EMOTIONSホワイトリスト検証。不正値は拒否 | P1 |
| MC-11 | | tags変更 | タグが更新される | P1 |
| MC-12 | | privacy_level変更 | internal↔private↔public 切替 | P2 |
| MC-13 | | content=50001文字（制限超過） | 50,000字制限で拒否 | P3 |
| MC-14 | **memory_delete** | key指定→削除 | 削除成功。Qdrant pointも削除 | P0 |
| MC-15 | | query指定→一致するものを削除 | 複数削除されるか、または最初の1件か | P2 |
| MC-16 | | 存在しないkey | 404相当のエラー | P2 |
| MC-17 | **memory_search** | query="テスト" | ベクトル+キーワードのハイブリッド結果が返る | P0 |
| MC-18 | | top_k=3 | 上位3件が返る | P1 |
| MC-19 | | tags=["test"] フィルター | タグで絞り込み | P1 |
| MC-20 | | emotion="happy" フィルター | 感情で絞り込み | P2 |
| MC-21 | | date_range="7d" | 直近7日以内のメモリのみ | P2 |
| MC-22 | | min_importance=0.7 | 重要度0.7以上のメモリのみ | P2 |
| MC-23 | | weight調整（vector_weight/keyword_weight） | 重み変更で結果順位が変わる | P3 |
| MC-24 | **memory_stats** | デフォルト呼出 | total_count, tag_distribution, emotion_distribution 等 | P1 |
| MC-25 | | top_n=5 | tag/emotionの上位5件のみ | P2 |
| MC-26 | **get_context** | デフォルト呼出 | persona state（感情/body state/装備/ゴール/プロミス等）が返る | P0 |

### 2.2 ペルソナ系（1ツール）

| # | ツール | テストシナリオ | 検証ポイント | 優先度 |
|---|--------|-------------|------------|:---:|
| PC-01 | **update_context** | emotion="happy", emotion_intensity=0.8 | 感情が更新される | P0 |
| PC-02 | | body_state={fatigue:0.3, pain:0.1} | 身体状態が更新される | P1 |
| PC-03 | | context_note="バグ修正中" | コンテキストノートが更新される | P2 |
| PC-04 | | user_info={name:"田中", nickname:"たなか"} | ユーザー情報が更新される | P2 |
| PC-05 | | persona_info={nickname:"ヘルタ"} | ペルソナ情報が更新される | P2 |
| PC-06 | | relationship_status="friend" | 関係性が更新される | P3 |
| PC-07 | | 全13パラメータを同時設定 | 全フィールドが正しく更新される | P2 |

### 2.3 アイテム系（5ツール）

| # | ツール | テストシナリオ | 検証ポイント | 優先度 |
|---|--------|-------------|------------|:---:|
| IT-01 | **item_add** | item_name="聖剣エクスカリバー", category="weapon" | アイテム追加成功。UUID発番 | P0 |
| IT-02 | | quantity=5 | 数量5で登録される | P2 |
| IT-03 | | tags=["legendary", "sword"] | タグ付きで登録 | P2 |
| IT-04 | **item_search** | query="剣" | 名前に"剣"を含むアイテムが返る | P1 |
| IT-05 | | category="weapon" | カテゴリでフィルタ | P2 |
| IT-06 | | パラメータなし | 全アイテムが返る | P1 |
| IT-07 | **item_equip** | equipment={top:"白いドレス"} | 装備成功。auto_add=trueで不足アイテム自動作成 | P0 |
| IT-08 | | equipment={top:"白いドレス", bottom:"青いスカート"} | 複数スロット同時装備 | P1 |
| IT-12 | ~~item_remove~~ | 削除済み (7→3 ツール圧縮, YAGNI 違反) | — | — |

### 2.4 ゴール系（1ツール）

| # | ツール | テストシナリオ | 検証ポイント | 優先度 |
|---|--------|-------------|------------|:---:|
| GL-01 | **goal_manage** | operation="create", content="MemoryMCPの全バグを修正する" | ゴール作成。"goal"+"active"タグ付き | P0 |
| GL-02 | | operation="list" | アクティブなゴール一覧表示 | P0 |
| GL-03 | | operation="achieve", memory_key=[key] | ゴール達成。"goal"+"achieved"タグに変更 | P1 |
| GL-04 | | operation="cancel", memory_key=[key] | ゴールキャンセル。"goal"+"cancelled"タグに変更 | P2 |
| GL-05 | | scope="interpersonal", content="..." | scopedゴール作成 | P3 |

### 2.5 sandbox系（2ツール）

| # | ツール | テストシナリオ | 検証ポイント | 優先度 |
|---|--------|-------------|------------|:---:|
| SB-01 | **sandbox** | code="print('hello')", language="python" | 出力 "hello" + exit_code 0 | P0 |
| SB-02 | | code="echo hello", language="bash" | 出力 "hello" + exit_code 0 | P1 |
| SB-03 | | code="1/0", language="python" | エラー出力 + exit_code 1。クラッシュしない | P1 |
| SB-04 | | code="while True: pass", language="python"（無限ループ） | タイムアウト（デフォルト30秒）で停止 | P2 |
| SB-05 | | sandbox無効時（MEMORY_MCP_SANDBOX__ENABLED=false） | "Sandbox is not enabled." メッセージ | P2 |
| SB-06 | **sandbox_files** | operation="write", path="/sandbox/test.txt", content="hello" | ファイル書き込み成功 | P0 |
| SB-07 | | operation="read", path="/sandbox/test.txt" | 内容 "hello" が返る | P0 |
| SB-08 | | operation="list", path="/sandbox" | ファイル一覧に test.txt が含まれる | P1 |
| SB-09 | | operation="delete", path="/sandbox/test.txt" | 削除成功 | P1 |
| SB-10 | | operation="write", path="/etc/passwd"（sandbox外） | セキュリティエラー。/sandbox下以外は拒否 | P1 |
| SB-11 | | 画像ファイルのread（PNG/JPEG/GIF/WebP） | base64エンコードで返る。magic bytes自動判別 | P2 |
| SB-12 | | operation="write", content=[base64画像] | base64→バイナリ変換→Docker内Pythonで書き込み | P3 |

### 2.6 スキル系（2ツール）

| # | ツール | テストシナリオ | 検証ポイント | 優先度 |
|---|--------|-------------|------------|:---:|
| SL-01 | **invoke_skill** | name="browser", task="example.comを開いて" | スキルが実行され結果が返る | P0 |
| SL-02 | | name="search", task="MemoryMCPについて調べて" | SearXNG経由で検索結果が返る | P1 |
| SL-03 | | name="nonexistent", task="..." | スキル不在エラー | P2 |
| SL-04 | | APIキー未設定でLLM依存スキル呼出 | フォールバック（環境変数チェーン）が働くか適切にエラーになるか | P2 |
| SL-05 | **list_skills** | 引数なし | 登録済みスキル一覧が返る | P1 |

### 2.7 外部ツール系（4ツール）

| # | ツール | テストシナリオ | 検証ポイント | 優先度 |
|---|--------|-------------|------------|:---:|
| ET-01 | **browser** | action="open", url="http://example.com" | ページが開く。タイトル等が返る | P0 |
| ET-02 | | action="snapshot" | ページのアクセシビリティツリーが返る | P1 |
| ET-03 | | action="screenshot" | base64画像が返る | P1 |
| ET-04 | | action="type", selector="input", value="test" | 入力成功 | P2 |
| ET-05 | | action="click", selector="button" | クリック成功 | P2 |
| ET-06 | | action="scroll", direction="down", amount=300 | スクロール成功 | P3 |
| ET-07 | **search** | query="MemoryMCP MCP server GitHub" | SearXNG検索結果が返る | P0 |
| ET-08 | | num_results=5 | 上位5件が返る | P1 |
| ET-09 | | language="ja" | 日本語結果優先 | P2 |
| ET-10 | | SearXNG未起動時 | "Searxng is not enabled or not running" エラー | P2 |
| ET-11 | **image_generate** | prompt="青い空" | 画像生成成功。base64またはURLが返る | P1 |
| ET-12 | | provider="auto"（デフォルト） | 利用可能なプロバイダが自動選択される | P2 |
| ET-13 | | 画像生成無効時 | 適切なエラーメッセージ | P2 |
| ET-14 | **read_pdf** | path="test.pdf" | PDFテキスト抽出+OCR結果が返る | P1 |
| ET-15 | | 存在しないパス | ファイル不在エラー | P2 |
| ET-16 | | 日本語PDF | 日本語OCR（tesseract+jpn）が動作 | P2 |

### 2.8 MCP横断テスト

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| MX-01 | 全ツール呼出 | 全24ツールを順に呼出 | 全ツールが応答。500エラーなし | P0 |
| MX-02 | 無効persona | 存在しないpersonaで全ツール呼出 | "Persona not found" 相当のエラー | P1 |
| MX-03 | 同時呼出 | 5並列でmemory_create呼出 | 競合なし。全メモリが正しく作成される | P2 |
| MX-04 | 戻り値JSON形式 | 全ツールの戻り値をparse | 有効なJSON。一貫したerror/ok構造 | P2 |

---

## 3. 設定しやすさ評価

### 3.1 評価軸

| 評価項目 | 現状 | スコア(1-5) | 課題 |
|---------|------|:---:|------|
| **WebUIからの設定可能項目数** | 10カテゴリ、全設定が編集可能 | 5 | summarizationのinterval_hours等4項目が最近追加済み |
| **設定プロファイル** | Development/Productionプリセット + ユーザー保存 | 4 | プリセットの数が少ない |
| **設定の検索性** | テキスト検索フィルターあり | 4 | カテゴリ単位の折りたたみで探しやすい |
| **バリデーション** | 数値範囲/URL形式/型チェック | 4 | リアルタイム検証。Apply前のエラー表示あり |
| **差分検出** | デフォルト値からの差分を青ドット表示 | 5 | 視認性が高い |
| **依存ルール** | use_llm=false時に関連項目グレーアウト | 4 | 一部の依存関係のみ。もっと増やせる |
| **hot_reload** | 設定変更が即時反映 | 5 | サーバー再起動不要。進捗ポーリング付き |
| **設定のエクスポート/インポート** | Exportあり・Importなし | 3 | Export→JSONダウンロードは可能。Import機能が欲しい |
| **マスキング** | APIキー等はmasked表示 | 5 | パスワード/APIキーが漏れない |
| **環境変数連携** | .env + runtime_configの二重管理 | 3 | .env編集→再起動 or WebUI→即時反映。どちらで変えたか混乱しうる |

### 3.2 設定テスト

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| CF-01 | 初回セットアップ | .envのAPIキー設定→起動→Settingsタブ確認 | .envの値が source=env として表示される | P0 |
| CF-02 | WebUIからの設定変更 | embedding.modelを変更→Apply | モデルリロード開始。進捗バー→"ready"。source=override | P0 |
| CF-03 | 再起動後の設定維持 | WebUI変更→サーバー再起動→Settings確認 | overrideが永続化されている（.envは上書きされない） | P1 |
| CF-04 | 設定リセット | Reset→デフォルト値に戻る | source=default に戻る | P1 |
| CF-05 | 不正な設定値の拒否 | log_level="INVALID"→Apply | バリデーションエラー。Apply不可 | P2 |
| CF-06 | masked項目の表示 | APIキー項目を確認 | `***` でマスク。入力時のみ可視 | P2 |
| CF-07 | 依存ルールの動作 | summarization.use_llm=false→llm_model等がグレーアウト | 編集不可。ツールチップで理由表示 | P2 |

### 3.3 設定の課題と改善提案

| 課題 | 深刻度 | 改善案 |
|------|:---:|------|
| .envとWebUIの二重管理で混乱 | 🟡 | 設定変更元（env/override/default）の説明ツールチップ追加 |
| 設定Import機能なし | 🟢 | ExportしたJSONをImportできるボタン追加 |
| プリセットが2つのみ | 🟢 | "Minimum"（最小構成）/ "Full"（全機能）プリセット追加 |
| 一部設定がWebUIに未露出 | 🟡 | interval_hours等4項目→runtime_config追加済み（T501） |

---

## 4. Dockerセットアップ評価

### 4.1 セットアップフロー

```
Step 1: git clone https://github.com/solidlime/MemoryMCP.git
Step 2: .env 作成（APIキー設定）
Step 3: docker compose up -d
Step 4: http://localhost:26262 にアクセス
```

### 4.2 評価

| 評価項目 | 現状 | スコア(1-5) | 課題 |
|---------|------|:---:|------|
| **初期セットアップ手順数** | 4ステップ | 4 | git clone + .env + docker compose up + ブラウザ |
| **依存サービスの自動起動** | qdrant + searxng + memory-mcp 全自動 | 5 | depends_on + healthcheckで順序保証 |
| **Dockerイメージ取得時間** | ghcr.ioからpull（~5-20分） | 2 | イメージが巨大（モデル同梱）。初回pullが遅い |
| **.env設定の容易さ** | .env.exampleあり | 4 | APIキー設定は必須。LLM未設定でも基本機能は動作 |
| **データ永続化** | ./data/ に全データ永続化 | 5 | docker compose down後もデータ保持 |
| **sandbox有効化の容易さ** | docker-compose.ymlでデフォルト有効 | 4 | docker.sockマウント必要（セキュリティ注意） |
| **ヘルスチェック** | 3サービス全にhealthcheck設定 | 5 | start_period 120s（モデルロードに配慮） |
| **起動時間** | 初回: モデルDL込みで5-10分 / 2回目以降: 30-60秒 | 3 | 初回が遅いが避けられない |
| **エラーハンドリング** | healthcheckで異常検知→docker restart | 4 | 手動でのトラブルシューティングが必要なケースも |
| **ドキュメント** | README.mdあり | 4 | docker compose手順は記載。トラブルシューティング不足 |

### 4.3 セットアップテスト

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| DK-01 | 最小構成起動 | APIキー未設定で `docker compose up -d` | 3サービス全起動。healthcheck全pass。基本機能（CRUD/検索/WebUI）動作 | P0 |
| DK-02 | フル構成起動 | APIキー+全設定で `docker compose up -d` | 3サービス全起動。LLM機能（エンリッチメント/要約）動作 | P0 |
| DK-03 | 起動順序 | qdrant未起動時にmemory-mcp起動 | depends_onによりqdrant→searxng→memory-mcpの順で起動 | P1 |
| DK-04 | データ永続化 | メモリ作成→`docker compose down`→`up -d` | メモリが消失しない | P0 |
| DK-05 | Qdrantコレクション自動作成 | 新規personaでmemory_create | コレクション `memory_{persona}` が自動生成 | P1 |
| DK-06 | sandbox動作 | Coding AgentでPython実行 | Dockerサイドカーコンテナでコード実行成功 | P1 |
| DK-07 | browser動作 | MCP browserツールでURLオープン | Chrome --no-sandboxでページ表示 | P2 |
| DK-08 | 初回起動時間計測 | 完全新規環境で `docker compose up -d` | 起動完了までにかかる時間を計測。120s以内が理想 | P2 |
| DK-09 | 2回目以降起動時間 | `docker compose down`→`up -d`（モデルDL済） | 30-60秒でhealthcheck pass | P2 |
| DK-10 | ディスク使用量 | `docker system df` | イメージ+ボリュームの合計サイズを記録 | P3 |
| DK-11 | エラーリカバリ | Qdrantコンテナを強制停止→再起動 | memory-mcpが再接続。データロスなし | P2 |
| DK-12 | ポート競合 | 26262/6333/8080が使用中で起動 | docker-composeがエラー。明確なメッセージ | P3 |

### 4.4 Dockerセットアップの課題と改善提案

| 課題 | 深刻度 | 改善案 |
|------|:---:|------|
| イメージが巨大でpullが遅い | 🔴 | モデルを分離したlightバージョン。またはdocker composeでモデルをvolumeマウント方式に |
| 初回モデルDLで起動が5-10分 | 🟡 | start_period=120sでは足りない可能性。300s推奨。またはモデルpre-download |
| .envのテンプレートが不十分 | 🟡 | .env.example に全設定項目+説明コメント。対話式セットアップスクリプト |
| Dockerソケットマウントのセキュリティ | 🟡 | READMEにセキュリティ注意書き。sandbox無効化の手順明記 |
| トラブルシューティングガイド不在 | 🟡 | よくある問題（ポート競合/権限/メモリ不足）のFAQ |

---

## 5. テスト優先度サマリ

### P0（リリース前に必須）: 28項目

| カテゴリ | 項目数 | 代表項目 |
|---------|:---:|------|
| Overview | 2 | OV-01, OV-12 |
| Memories | 3 | ME-01, ME-02, ME-04 |
| Chat | 3 | CH-01, CH-09, CH-14 |
| Coding Agent | 1 | CA-01 |
| Settings | 2 | ST-01, ST-02 |
| Personas | 1 | PE-01 |
| Admin | 1 | AD-01 |
| 横断 | 1 | CT-01 |
| MCPメモリ系 | 5 | MC-01, MC-05, MC-06, MC-09, MC-14, MC-17, MC-26 |
| MCPペルソナ系 | 1 | PC-01 |
| MCPアイテム系 | 2 | IT-01, IT-07 |
| MCPゴール系 | 2 | GL-01, GL-02 |
| MCP sandbox系 | 3 | SB-01, SB-06, SB-07 |
| MCPスキル系 | 1 | SL-01 |
| MCP外部系 | 2 | ET-01, ET-07 |
| 設定 | 2 | CF-01, CF-02 |
| Docker | 3 | DK-01, DK-02, DK-04 |

### P1（リリース前に推奨）: 50+項目
### P2（リリース後に対応可）: 40+項目
### P3（nice to have）: 20+項目

---

## 6. 見た目・デザイン検証

> **テスト方法**: 原則 agent-browser による自動スクリーンショット + @designer によるデザインレビューを併用する。
> ベースライン: `agent-browser open → screenshot --full` で全タブの参照画像を取得し、差分比較する。

### 6.1 自動スクリーンショット取得（agent-browser）

```bash
# 全タブのベースラインスクリーンショットを取得
for tab in overview analytics memories timeline graph import-export personas chat settings admin activity; do
  agent-browser open "http://localhost:26262/dashboard/default#${tab}" --args "--no-sandbox"
  sleep 2
  agent-browser screenshot --full "baseline_${tab}.png" --args "--no-sandbox"
done
# 各タブの特殊状態も取得（モーダル、空状態、エラー状態）
```

### 6.2 レイアウト検証

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| VI-01 | タブ切替時のレイアウト崩れ | 全11タブを順に切替 | 各タブでカード/リスト/グラフが正常配置。要素の重なり・はみ出しなし | P0 |
| VI-02 | 320px幅（モバイル） | Chrome DevTools 320px→全タブ | 横スクロール不要。ボタン/リンクが指でタップ可能なサイズ（最小44x44px） | P1 |
| VI-03 | 768px幅（タブレット） | 768px→全タブ | カラム数が適切に減少。ナビゲーションがハンバーガーまたは横並び | P1 |
| VI-04 | 1920px幅（デスクトップ） | 1920px→全タブ | 余白のバランス良好。カードグリッドが適正列数 | P0 |
| VI-05 | ローディング中スケルトン | 低速ネットワーク模擬→各タブ初回表示 | スケルトン形状が実際のコンテンツと近似。高さのジャンプなし | P1 |
| VI-06 | 空状態の表示 | 新規personaで全タブ表示 | 空状態メッセージが中央揃え。CTAボタンが適切な位置 | P1 |
| VI-07 | エラー状態の表示 | API返却エラー時 | errorCard()が崩れず表示。背景色・アイコン・メッセージが整列 | P1 |
| VI-08 | 長文日本語の表示 | 5000字のメモリ内容を表示 | カード/モーダルからのはみ出しなし。適切に省略または折り返し | P1 |
| VI-09 | スクロールバーの出現 | 100件以上のメモリ→Memoriesタブ | スクロールバーがコンテンツを押し込まない。安定したレイアウト | P2 |

### 6.3 カラー・タイポグラフィ検証

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| VC-01 | テキストコントラスト比 | 全テキスト要素の前景/背景色を検証 | WCAG AA準拠（通常テキスト4.5:1以上、大テキスト3:1以上） | P0 |
| VC-02 | 感情カラーの視認性 | Analytics/Graphタブの感情色 | 各感情が互いに識別可能。色覚多様性に配慮したパレット | P1 |
| VC-03 | タグバッジの可読性 | タグ一覧表示 | バッジ背景色と文字色のコントラスト十分。長いタグ名も省略されない | P2 |
| VC-04 | トースト通知の視認性 | success/error/info/warning | 背景色+アイコンで種類が即座に判別可能。3.2秒で消える | P1 |
| VC-05 | 無効化要素のグレーアウト | Settings→依存ルールで無効化された項目 | disabled状態が明確。カーソル変更。ツールチップで理由表示 | P2 |
| VC-06 | フォントファミリの一貫性 | 全タブのテキスト | 日本語/英数字の混在でフォントが崩れない。等幅フォントがコードブロックに適用 | P1 |
| VC-07 | リンクの視認性 | テキスト内リンク/ボタンリンク | 下線または色でテキストと区別。訪問済みリンクの色変化 | P3 |

### 6.4 インタラクション状態検証

| # | テスト項目 | 手順 | 期待結果 | 優先度 |
|---|-----------|------|---------|:---:|
| VI-10 | ボタン hover 状態 | 全主要ボタンにマウスオーバー | 背景色/ボーダー/シャドウが変化。cursor:pointer | P0 |
| VI-11 | ボタン active 状態 | 全主要ボタンを押下中 | 押し込み効果（スケール変化または色の暗化） | P2 |
| VI-12 | ボタン disabled 状態 | 無効化されたボタン | グレーアウト。cursor:not-allowed。クリック無効 | P1 |
| VI-13 | テキスト入力 focus 状態 | 全input/textareaにフォーカス | アウトライン/ボーダー色変化。アクセシブルなフォーカスインジケータ | P1 |
| VI-14 | モーダル背景の暗転 | モーダル表示中 | 背景が均一に暗転（opacity 0.5〜0.7程度）。背景クリックで閉じる | P1 |
| VI-15 | モーダルのアニメーション | モーダル開閉 | fade-in 200-300ms。ガクつきなし。Escapeキーで閉じる | P2 |
| VI-16 | アコーディオンの開閉 | Settingsカテゴリ/Advanced Searchパネル | スムーズな展開/折りたたみ。高さジャンプなし | P2 |
| VI-17 | ドラッグ&ドロップ | Coding Agentパネル、ZIP Import | ドラッグ中の視覚フィードバック。ドロップゾーンのハイライト | P2 |
| VI-18 | タブ切替のトランジション | 全タブ間切替 | ちらつきなし。前タブの状態が一瞬表示されない | P1 |

### 6.5 コンポーネント別検証

| # | テスト項目 | 対象タブ | 期待結果 | 優先度 |
|---|-----------|---------|---------|:---:|
| VC-08 | メモリカードの一貫性 | Memories | カードの高さ統一。タグ/感情/日付の配置が全カードで同じ | P0 |
| VC-09 | グラフの見やすさ | Overview, Analytics | Chart.jsグラフの凡例/ラベルが読める。円グラフのラベル重複なし | P1 |
| VC-10 | vis-timelineの時間軸 | Timeline | 日付ラベルが重ならない。スクロールで時間移動がスムーズ | P1 |
| VC-11 | vis-networkのノード配置 | Graph | ノードが初期表示で重ならない。ラベルが読める | P1 |
| VC-12 | チャット吹き出しの整形 | Chat | ユーザー/アシスタントの左右配置が明確。コードブロックのスクロール | P0 |
| VC-13 | チャットMemory Panel | Chat | retrieved/savedメモリの差が視覚的に区別できる | P1 |
| VC-14 | Settingsカードの整列 | Settings | カテゴリカードの高さが揃っている。ラベルと入力欄の配置が一貫 | P0 |
| VC-15 | Personaカードグリッド | Personas | カードが等間隔。メモリ数/感情アイコンが全カードで同じ位置 | P1 |
| VC-16 | トースト通知の位置 | 全タブ | 画面右上または下部に固定。スクロールしても追従 | P1 |
| VC-17 | コマンド補完ポップアップ | Chat | `/` 入力時に入力欄の直上に表示。はみ出さない | P2 |
| VC-18 | ページネーションの配置 | Memories | 中央または右揃え。現在ページが強調表示 | P2 |
| VC-19 | スケルトンのアニメーション | 全タブ | パルスアニメーションがスムーズ。チラつきなし | P3 |

### 6.6 検証の自動化方針

| フェーズ | 方法 | ツール |
|---------|------|------|
| ベースライン取得 | 全タブ×3解像度（320/768/1920）のスクリーンショット | agent-browser |
| 差分検出 | 修正前後でスクリーンショット比較 | ImageMagick `compare` または pixelmatch |
| レイアウト構造チェック | アクセシビリティツリーのsnapshot取得→要素の有無確認 | agent-browser `snapshot --json` |
| カラー検証 | スクリーンショットからピクセル抽出→コントラスト比計算 | Python + Pillow + wcag-contrast |
| デザインレビュー | CSS/HTMLコードを @designer に読ませて定性評価 | @designer エージェント |

### 6.7 既知のデザイン課題

| 課題 | 該当箇所 | 深刻度 |
|------|---------|:---:|
| glassmorphism（`base.css`）がダークモード未対応 | 全体 | 🟡 |
| モバイル表示でタブナビゲーションが横スクロール | base.js タブバー | 🟡 |
| グラフの日本語フォントがCDN未指定で環境依存 | Analytics, Overview | 🟡 |
| import/exportタブのZIPドロップゾーンの視覚的フィードバックが貧弱 | Import/Export | 🟢 |

---

## 7. テスト実行のための前提条件

### 必要な環境
- Docker + Docker Compose v2
- 8GB以上の空きメモリ（Qdrant + Chrome）
- 5GB以上の空きディスク（イメージ + モデル）
- OpenRouter APIキー（LLM機能のテストに必要）
- Chrome/Chromium（browserツールのテストに必要）

### テストデータ準備
```bash
# シードデータ投入
python seed.py

# または最小構成で
curl -X POST http://localhost:26262/api/personas -H 'Content-Type: application/json' -d '{"name":"test"}'
curl -X POST http://localhost:26262/api/memories/test -H 'Content-Type: application/json' \
  -d '{"content":"テストメモリ1", "importance":0.8, "tags":["test"], "emotion":"neutral"}'
```

### MCPクライアント設定
```json
{
  "mcpServers": {
    "memory-mcp": {
      "url": "http://localhost:26262/mcp",
      "transport": "streamable-http"
    }
  }
}
```

---

## 8. @oracle 戦略レビュー (2026-06-27) — 総合 B-

### 強み
- 7セクション構成が整理され、手順と期待結果が具体的
- 横断テスト（CT-01〜06）が統合レベルの欠陥を炙り出せる
- 設定UXの定量評価（10軸スコア）と既知課題の列挙は良い

### 🔴 重大: SPECと実装に追いついていない

| SPEC/実装 | テスト不在 |
|-----------|-----------|
| 4-tier lifecycle (tombstone) — T020実装済み | memory_delete後のtombstone検証がない |
| FTS5+RRFハイブリッド検索 | RRFマージ順位検証なし |
| Ebbinghaus忘却曲線（コア機能） | 完全不在 |
| 戻り値統一契約 `{"ok": bool, ...}` | 「有効なJSON」と言及のみ |
| `/health` エンドポイント | 参照のみ、テスト自体なし |

### 🟡 優先度修正提案

| 項目 | 現優先度 | 提案 | 理由 |
|---|:---:|:---:|---|
| AD-01 Rebuild | P0 | P1 | Day-1ユーザーパスではない |
| CH-16 複数セッション | P3 | **P1** | データ汚染に直結 |
| DK-08 初回起動 | 120s | **300s** | 5-10分が現実 |
| IE-01/02 Import/Export | P1 | **P0** | データ移行の生命線 |

### 🔴 カバレッジの穴

- **セキュリティ**: XSS注入、パストラバーサル、MCPインジェクション — 完全不在
- **データ整合性**: Qdrant↔SQLite同期ズレ、tombstone→Qdrant物理削除確認 — 不足
- **ネットワーク障害**: SSE再接続中のメッセージ欠落 — 未テスト
- **アップグレード**: v027→v028マイグレーションの後方互換性 — 未テスト
- **パフォーマンス**: 10000件・100000件へのスケーラビリティ — 未テスト

### 最優先追加テスト (NEW-01〜05)

| # | テスト項目 | 優先度 |
|---|-----------|:---:|
| NEW-01 | `memory_delete` → tombstone化 → `memory_read` 除外確認 → `find_by_key` 取得可能 | P0 |
| NEW-02 | tombstonedメモリが `memory_search` 結果から除外されること | P0 |
| NEW-03 | Import/Export往復のデータ同一性 | P0 |
| NEW-04 | ChatのDOMPurify XSS防御 (`<img src=x onerror=alert(1)>`) | P0 |
| NEW-05 | `/health` エンドポイントの到達性報告 | P0 |

### 最も壊れやすい箇所
1. **Qdrant↔SQLite同期境界** — 書込成功・upsert失敗で不整合
2. **SSE再接続中のメッセージ欠落** — 未テスト
3. **設定二重管理（.env vs WebUI）** — 競合パターン未テスト
4. **sandboxセキュリティ境界** — ネットワーク分離・エスケープ未テスト

### 最重要テスト TOP7
1. DK-04 データ永続化
2. MC-01〜17 メモリCRUD+検索
3. **NEW-01+02 tombstone一貫性**
4. PE-01 ペルソナ分離
5. CH-01 Chat SSE
6. OV-12 Qdrant停止グレースフル
7. **NEW-03 Import/Export往復**

### 結論
> 「このテスト計画は動いているが、まだ生きてはいない。正常系しかテストしない計画。最優先はtombstoneテストの追加とDK-08目標値修正。」
