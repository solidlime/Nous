# キャラ逸脱の蓄積・傾向補正（記憶方式） — Design

Date: 2026-09-05
Status: approved (brainstormingで方式B承認済み)
Scope: CharacterJudgeの違反判定を記憶として蓄積し、傾向補正する

## 背景・現状

- Author's Noteは完全撤去済み (1b30a510)。毎ターン無フィルタ注入の永続文字列はもうない。
- CharacterJudge (`nous/application/chat/character_judge.py:35-51`) は文脈なし判定器: persona抜粋[:2000]+応答[:2000]のみ、temp 0.0/max 200。MemoryLLMとDoneSSE後に並走 (`nous/application/chat/pipeline/post.py:176-205`)。
- 判定結果はCharacterFlagSSEで表示のみ (`post.py:280-281`)。蓄積されないため、同じ逸脱の繰り返しに傾向補正が効かない。
- MemoryLLM側 (`nous/application/chat/memory_extractor.py:254-267`) は全文ターン文脈 (user/assistant各[:500]、tool_calls_log付き) を持ち、factsは一人称視点が規約 (`nous/application/chat/memory_prompts.py:60`)。

参照: exp-3接合点調査 (post.py:180 payloadが接合点)。

## 目的・成功条件

- 目的: 逸脱判定を反省文として記憶に蓄積し、次ターン以降の自己補正に効かせる。
- 成功条件:
  1. 違反ターンがfactsに一人称反省文として残る (tags/importance付き)。
  2. 蓄積driftが次ターン以降のプロンプトに載る (通常recall + 直接注入)。
  3. 古いdriftは自動で消える (期限 + 減衰)。
- 非目的: judgeの高精度化、文脈付き判定化、新規スコアラ、新規TTL列、Author's Note復活。

## 設計 (方式B: 記憶方式)

### 1. 記録 (judgeは判定専念)

- judgeは変えない (文脈なし・判定のみ)。
- `post.py:189`横: gather後にjudgment (violation/detail) を捨てず、`run_memory_llm`側payloadに`drift`として渡す。
  - payloadは現状 `{user, assistant}` (`post.py:180`)。`drift={"violation":..., "detail":...}` を追加。violationがnone/Noneならキー自体付けない。
  - `run_memory_llm` (`memory_extractor.py:245`) → `MemoryLLM.process`へ伝達。伝達方式 (assistant_response末尾への`[CharacterDrift: violation/detail]`付記 vs process引数追加) はwriting-plansで確定。
- `memory_prompts.py`にdriftルール追記: payloadにdriftがあればfactsに反省文を1件だけ作る。なければ作らない (重複禁止)。
  - content: 一人称独白の反省文 (「私は〜すべきだった」形式。`memory_prompts.py:60`規約)。
  - tags: `["character_drift", violation種別]` (種別=tone/compliance/character)。
  - importance: 0.8-0.9 (goal 0.75/約束0.8の上。前例 `memory_extractor.py:289,325,365`)。
- スマートアップサート (類似度>0.85スキップ) は既存のまま。同種driftの連投は重複排除される。

### 2. 想起 (既存仕組みのみ・二段構え)

- (a) 通常recall: 変更なし。高importanceが複合スコア (`memory_retriever.py:108`、recency 0.3/importance 0.3/relevance 0.4、RRF k=5.0) で素直に浮上。
- (b) 直接注入: プロンプト構築時に `get_by_tags(["character_drift"], include_consumed=False)` で最新1件 (created_at降順) をcontext_section末尾に「内面の違和感: …」として注入 (前例: `_tools_persona.py:89-92`のphysical/mental直取り)。valid_until期限切れ・該当なしなら注入しない。新規スコアラなし。
- skipped: タグブースト重み新設。add when: (a)(b)で取りこぼしが実測されたら。

### 3. 減衰消去 (必須)

- 既定: 期限付き保存 `valid_until=now+7日` (bitemporal + `memory_search_repo.py:60-65`のvalid_atフィルタが除外。前例: `docs/memory_features.md:220`矛盾時自動付与)。
  - `create_memory`経路でvalid_untilを渡せること (repository `domain/memory/repository.py:118`は対応済み。service経路の受付はwriting-plansで確認、なければ最小拡張)。
- 長期放置分はdecayワーカー (FSRS、`decay_worker.py:69-131`、strength<0.2かつ30日不活性→archived) → consolidation回収 → 論理削除 (tombstoned) で自然消滅。
- consume-onceは使わない (傾向補正には複数ターンの参照が必要なため)。
- 明示削除の前例 (`reflection.py:74`のdelete_memory) は、誤記録時の手動修正手段として残す。

### 4. 表示

- CharacterFlagSSEは維持 (当該ターンの違反表示)。
- 表示文を「⚠ 内面に違和感(種別)」形式に統一 (`nous/api/http/static/chat/chat-send.js`の警告トースト表示名)。
- skipped: ダッシュボードへのdrift一覧表示。add when: 運用で必要になったら。

### 5. アーキテクチャ・変更点 (予想)

- `nous/application/chat/pipeline/post.py`: judgment→payload受け渡し。
- `nous/application/chat/memory_extractor.py` + `memory_llm.py`: drift伝達・保存 (valid_until付き)。
- `nous/application/chat/memory_prompts.py`: drift→反省文ルール。
- プロンプト構築側 (context_loaderまたはprepare): (b)直接注入。
- `nous/api/http/static/chat/chat-send.js`: 表示名統一。
- 触らない: `character_judge.py` (判定専念)、`memory_retriever.py` (重み不変)、`engine.py`、schema (新規列なし)。

### 6. テスト

1. 記録: violationあり→factsに反省文1件 (tags `character_drift`+種別、importance 0.8-0.9、一人称)。violation none/None→反省文なし。
2. 減衰: valid_until期限切れdriftは検索・直接注入の双方から除外。
3. 表示名: CharacterFlagSSEの表示が「⚠ 内面に違和感(種別)」形式。
4. 既存: 関連スイート全pass (pipeline/persona/post/prompt)。

## 代替案とトレードオフ (検討済み)

- 案A (judgeに文脈を持たせる): 却下。判定器と記憶生成の責務混在、コスト増。文脈を持つ側 (MemoryLLM) に寄せる方が既存構造に合う。
- 案C (専用テーブル・TTL列新設): 却下。bitemporal + decay + tombstoneの既存3種で足りる (YAGNI)。
