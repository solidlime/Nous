# 計画書: 日記・矛盾整理・自走調査 — wiki 層の 3 拡張

2026-11-10 / kanban #38 #39 #40

## 1. 背景

`docs/superpowers/plans/2026-11-07-wiki-dreaming.md` で「記憶の整理先 = まとめ wiki」を作った。
次の 3 点が欠けている（ユーザー要望 2026-11-10）:

1. **日記**がない。日々の流れを 1 日 1 ページで残したい（整理の入口にもなる）。
2. **矛盾の整理**がない。ページ間で「同じ事実を違う値で書いている」状態を放置している。
3. **わからないことを放置している**。編纂中に根拠が足りない箇所が出ても、黙って薄い記述で埋める。

ユーザー決定:
- 日記は **wiki ページとして日次**（専用ストレージは作らない）
- 矛盾整理は **wiki 層も記憶層も**やる。ただし**コストを抑える**
- わからないことは **worker が自分で調べる**（ユーザーに聞くのは最終手段）
- 実行は **既存の 03:00 JST サイクルに相乗り**（新ワーカーを作らない）

## 2. 設計方針（決定）

| 論点 | 決定 | 理由 |
|---|---|---|
| 日記の実体 | `wiki/journal-YYYY-MM-DD.md` | 既存の WikiStore / index / 検索 / ダッシュボードにそのまま乗る |
| ページのタグ | frontmatter に `tags:` を追加 | 日記を `tags: journal` で一括参照できる。日付だけに依存しない |
| 矛盾検出（wiki） | **既存の編纂 LLM 呼び出しの出力を拡張** | LLM 呼び出し回数 +0。出力トークンだけ増える |
| 矛盾検出（記憶） | 週次・上限付きの掃除。既存 `classify_contradiction` を再利用 | 新規ドメインロジックを書かない |
| 自走調査 | `max_tool_calls`(3) で上限。ツール実行 1〜3 回 | 登録済み MCP ツールのみ。無ければ何もしない | 外部 SaaS の鍵管理を増やさない。経路が 1 本 |
| 未解決の質問 | 記憶として記録（`tags: open-question`）+ 日記の「未解決」に列挙 | 新テーブル / 新 UI を作らない |
| 実行順 | journal → 編纂 → 矛盾 → 調査 | 1 サイクル内で完結。失敗は前段に閉じる |

### コスト見積（1 日あたり）

| 工程 | LLM 呼び出し | 検索 | 備考 |
|---|---|---|---|
| 日記 | +1 | 0 | 前日分。記憶が 0 件なら skip |
| 編纂（既存） | 2 | 0 | 変更なし |
| 矛盾（wiki） | +0 | 0 | 既存呼び出しの出力に `conflicts` を足すだけ |
| 矛盾（記憶） | ≤10/週 | 0 | 候補ペアの事前フィルタで LLM 前に絞る |
| 調査 | +1（結果がある日だけ） | ≤3/日 | 15 秒 timeout、失敗は無視 |

合計: 平常日 +1〜2 呼び出し。既存の 2 トピック編纂と同程度で、**新規の重い処理は無い**。

## 3. データモデル

### 3.1 ページのタグ（#38）

```python
@dataclass(frozen=True)
class WikiPage:
    slug: str
    title: str
    body: str
    project: str | None = None
    sources: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()          # 新規
    updated: str | None = None
    links: tuple[str, ...] = field(default_factory=tuple)
```

- `render_page` は `tags: journal, 2026-11` の 1 行（空なら書かない）
- `parse_page` は `_parse_sources` と同じカンマ区切り
- 検証: `^[a-z0-9][a-z0-9_-]{0,23}$`、最大 8 個。壊れた値は**捨てる**（ページ全体を落とさない）
- `index.md` には出さない（行数契約 MAX_INDEX_LINES を守る）

### 3.2 日記ページ（#38）

slug: `journal-{YYYY-MM-DD}`（JST）。`tags: journal`。project は付けない。

本文の型（LLM にそのまま書かせる。見出しは固定）:

```markdown
## やったこと
## 感想
## 決めたこと
## 引っかかったこと
## 未解決
```

`## 感想` は必須。事実の列挙ではなく「その日に起きたことに対して何を感じたか」。
ここが後段の感情・体調の更新の入力になる（§3.4）。

sources = その日の記憶キー（最大 60、`created_at` 昇順）。0 件なら**ページを作らない**（空ページを増やさない）。

### 3.3 矛盾の表現（#39）

wiki 編纂の応答 JSON に 2 つのキーを足す:

```json
{"pages": [...],
 "conflicts": [{"a": "slug", "b": "slug", "kind": "value|fact|scope",
                "detail": "何がどう食い違うか", "resolved": true}],
 "questions": [{"query": "外部で確かめたいこと", "why": "なぜ必要か", "topic": "slug"}]}
```

- `resolved: true` … そのページ本文に「以前は X、今は Y（<date> 時点）」として書き直し済み
- `resolved: false` … 記憶に `open-question` タグで記録し、日記の「未解決」に列挙
- 既存の `pages` 形式は不変（後方互換。無いキーは空扱い）

## 4. コンポーネント

### 3.4 日記 → 感情・体調の反映（#38）

日記を書いた直後に 2 回目の LLM 呼び出しで状態を抽出する（本文 + 材料を渡す）:

```json
{"emotion": "満足", "emotion_intensity": 0.7,
 "physical_state": "少し眠い", "mental_state": "落ち着いている",
 "body_state": {"fatigue": 0.6}}
```

適用は既存のサービスにそのまま渡す（クランプはサービス側の責務なので自前で正規化しない）:

- `persona_service.update_emotion(persona, emotion, intensity, context="journal:<slug>")`
- `persona_service.update_physical_state(persona, physical_state=..., mental_state=..., **body_state)`

抽出に失敗したら**何もしない**（日記は残る）。`journal_apply_state=false` で切れる。

### 4.1 `nous/infrastructure/wiki/store.py`（#38）

- `WikiPage.tags` 追加 / `render_page` / `parse_page` / `write_page(tags=)` / `_parse_tags` / `_validate_tags`
- 8KB 上限・slug 検証は不変

### 4.2 `nous/application/workers/wiki_worker.py`（#38 → #39 → #40）

呼び出し順（`run_cycle`）:

```
1. _compile_journal(ctx, persona, store, now)     # #38
2. for topic in _select_topics(...)[:topics_per_cycle]: _compile_topic(...)   # 既存
3. _apply_conflicts(...)   # #39（編纂の戻り値をそのまま使う。追加呼び出しなし）
4. _resolve_questions(...) # #40（questions があるときだけ）
```

- `_compile_journal`: 前日（JST）の記憶を集め、topic=`journal` として `_ask_and_parse` を呼ぶ。プロンプトは `_build_prompt` の派生 `_build_journal_prompt`（見出し固定・`sources` 制約・`conflicts` を出さない）
- `_apply_conflicts`: `pages` 適用後に `conflicts` を処理。`resolved=false` は `_record_open_question`
- `_record_open_question`: `memory_repo` に `tags=("open-question", "project:<slug>")` で 1 件書く。同一質問の重複は本文ハッシュで抑止

### 4.3 `nous/application/wiki/research.py`（新規, #40）

**登録済みの MCP ツールだけを使う。無ければ何もしない。**（直接 ddgs を叩かない）

```python
async def research(ctx, persona: str, question: str, *, max_calls: int = 3) -> dict:
    """登録 MCP ツールで調べる。
    戻り値: {"tool": str|None, "calls": [(tool, args, result_excerpt)], "findings": str}
    ツールが 1 つも無ければ {"tool": None, ...}（何もしない）。
    """
```

手順:

1. 登録サーバーを引く: `ChatConfigFileRepository(settings.data_root).get(persona).mcp_servers`
   （herta 本番では `mcp-hub` http://nous-mcp-hub-1:26263/mcp が登録済み）。
2. `MCPClientPool(configs)` を開いて `list_all_tools()`。**0 件なら即 return（何もしない）**。
3. LLM に「質問 + ツール一覧（name と description 先頭 120 文字）」を渡し、1 手ずつ実行させる:
   `{"tool": "<name>", "args": {...}}` / `{"answer": "..."}` / `{"give_up": true}`。
   ツール結果は 2KB に切り詰めて履歴に戻す。`max_calls`(3) で打ち切り。
4. 得た findings（と URL があればそれ）を `_build_research_prompt` でページに追記:
   本文末尾に `## 外部情報` + `- [title](url)`。**URL を必ず残す**。URL が無い応答は採用しない。
5. 監査イベント: `wiki.research`（question / tool / calls / hits）、ツールが無ければ
   `wiki.research skipped: no mcp tool` を 1 行（何もしないことの記録）。

失敗（接続不能・タイムアウト・LLM の不正応答）は warning と監査のみ。ページ書き換えは行わない。

### 4.4 設定（`nous/config/settings.py` の `WikiConfig`）

| キー | 既定 | 意味 |
|---|---|---|
| `journal_enabled` | `true` | 日記を作るか |
| `journal_apply_state` | `true` | 感想から感情・体調を更新するか |
| `journal_max_sources` | `60` | 日記 1 ページの材料上限 |
| `conflict_check_enabled` | `true` | 編纂時の矛盾検出を頼むか（プロンプトに節を足す） |
| `memory_conflict_max_pairs` | `10` | 週次掃除の LLM 上限 |
| `memory_conflict_interval_hours` | `168` | 週次掃除の間隔 |
| `research_enabled` | `false` | 自走調査（登録 MCP ツールがある場合のみ動く。mcp-hub 3 段呼び出し未対応のため既定 off） |
| `max_research_per_cycle` | `3` | 1 サイクルで調べる質問数 |
| `research_max_tool_calls` | `3` | 1 質問あたりのツール実行上限 |

## 5. リスクと対策

| リスク | 対策 |
|---|---|
| 日記が薄い/水増しになる | 記憶 0 件は skip。材料が 5 件未満なら「短く書け」をプロンプトに入れる |
| 矛盾検出で LLM が勝手に事実を消す | 消させるのは「同じスロットの古い値」だけ。本文から節を丸ごと落とすのは禁止（プロンプト + `_apply_page` の 8KB/検証で担保） |
| 週次掃除のコスト膨張 | 候補ペアを決定的に絞る（同 project + 本文の Jaccard ≥ 0.5 + 異なる数値を含む）。LLM は上限 10 でハードストップ |
| 検索が落ちる/遅い | ツール未登録なら**何もしない**（発動しない）。接続失敗・timeout は warning のみで編纂結果を残す |
| 外部情報が古い/誤り | 必ず URL を残す。`## 外部情報` は本文の主張と分離し、後から検証できる形にする |
| 日記 slug 衝突（同じ日に 2 回） | `journal-YYYY-MM-DD` は上書き（1 日 1 ページ）。サイクルが 2 回走っても増えない |

## 6. 検証

- unit: タグ roundtrip（render→parse→同値、不正値の切り捨て）/ 日記セレクタ（JST 境界・0 件 skip・上限）/ 感想→状態反映（`journal_apply_state=False` で呼ばれない・抽出失敗で何もしない）/ conflicts パース（resolved 有無・壊れた JSON）/ open-question の重複抑止 / research（登録 0 件で何もしない・max_calls 打ち切り・URL 無し応答を採用しない）/ 週次掃除の候補フィルタと上限
- integration: フェイク provider で 1 サイクル回し、日記 + 編纂 + 矛盾 + 調査が順に走り、`wiki.compiled` / `wiki.conflict` / `wiki.research` / `wiki.question` イベントが残る
- 本番: 手動トリガ → `/data/persona/herta/wiki/journal-*.md` ができ、index に載り、`tags: journal` が入り、回答に URL がある

## 7. 段階計画

- **#38 タグ + 日記（+ 感想による状態反映）**: store の tags、journal 選定、プロンプト、`_apply_journal_state`、テスト
- **#39 矛盾整理**: プロンプト拡張 + conflict 適用 + 週次記憶掃除
- **#40 自走調査（登録 MCP ツール経由）**: research.py、question 解決、日記の「未解決」連携
