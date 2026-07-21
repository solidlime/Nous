# SPEC — 内臓スキル5種 自律動作テスト (2026-07-21)

## 背景
Nous の組み込みスキル（auto-memory, recall-weaver, mood-sync, goal-coach, image-gen）が `tencent/hy3:free` モデルで自律動作するか検証する。現在、herta ペルソナの設定に不備があり（provider 不一致、enabled_skills 欠損）、修正とプロンプト最適化が必要。

## スキル→ツール マッピング
| スキル | 発動トリガー | invoke_skill後ツール | 検証基準 |
|--------|------------|---------------------|---------|
| auto-memory | ユーザーの好み・習慣・決断の表明 | memory_create | 引数content, importance, tagsが適切 |
| recall-weaver | 過去の会話への言及 | memory_search | 引数query, top_kが適切 |
| mood-sync | 感情の動き・関係性の変化 | update_context | emotion, body_state等が適切 |
| goal-coach | 目標・決意の表明 | goal_manage | operation, scope, contentが適切 |
| image-gen | 感情変化・外見変化・画像依頼 | image_generate | prompt, self_portrait, modeが適切 |

## 合格条件（全スキル共通）
1. LLM がユーザーの明示的指示なしに `invoke_skill('<name>')` を呼び出すこと
2. invoke_skill の結果を受け取った後、対象ツールを正しい引数で呼び出すこと
3. ツール呼び出しが成功し、適切な結果が返ること

不合格パターン:
- スキル名をテキストで言及するが invoke_skill を呼ばない
- invoke_skill は呼ぶが対象ツールを呼ばず、代わりに「〜しますね」とテキストで説明する
- ツールを呼んでも引数が不十分・不適切

## 修正対象
### P0: 設定修正
- `data/persona/herta/config.json`: provider "anthropic" → "openrouter"
- `data/persona/herta/config.json`: enabled_skills 修正（"search","auto-self-portrait"削除、"image-gen"追加）

### P1: プロンプト最適化
- `nous/application/chat/pipeline/prompt.py`: TOOL_USAGE_GUIDELINES の強化
- スキル YAML frontmatter description の改善（トリガー条件をより明示的に）
- 場合により tool_choice 強制の検討

### P2: テスト実行
- WebUI API (`POST /api/chat/herta`) 経由で5種のトリガーメッセージを送信
- SSE ストリームから tool_call イベントを抽出し検証
- 結果をドキュメント化

## テストメッセージ案
| スキル | トリガーメッセージ |
|--------|------------------|
| auto-memory | 「私はコーヒーが大好きで、毎朝ブラックで飲んでるんだ」 |
| recall-weaver | 「前に話したこと覚えてる？あのプロジェクトの話」 |
| mood-sync | 「今日は本当に嬉しいニュースがあったんだ！」 |
| goal-coach | 「来月から毎日ジムに通おうと思ってるんだよね」 |
| image-gen | 「そういえば今どんな格好してるの？見せてよ」 |

---

## テスト結果 (2026-07-22 実行)

### 使用モデル: `nvidia/nemotron-3-ultra-550b-a55b:free`
> 当初の `tencent/hy3:free` は無料期間終了のため使用不可（404）。
> `qwen/qwen3-coder:free` も同様に無料期間終了。
> Nemotron 3 Ultra (55B active, 1M context) でテスト実施。

### 設定変更
| 項目 | 変更前 | 変更後 |
|------|-------|--------|
| provider | `anthropic` | `openrouter` |
| model | `tencent/hy3:free` | `nvidia/nemotron-3-ultra-550b-a55b:free` |
| temperature | `0.7` | `0.0`（ツール呼び出し決定論的動作のため） |
| enabled_skills | `search, auto-self-portrait` 含む | 5種のみに整理、`image-gen` 追加 |

### プロンプト変更
- `nous/application/chat/pipeline/prompt.py`:
  - `TOOL_USAGE_GUIDELINES`: `<tool_usage>` ブロック化、具体的ツール名列挙、禁止事項明記
  - スキルヘッダー: 「invoke_skillで呼び出せ」を明示
  - 末尾リマインダー: 3連命令形「テキストだけで済ませるな。ツールを呼べ。」

### テスト結果
| # | スキル | invoke_skill | 対象ツール呼出 | 合格 | 備考 |
|---|--------|-------------|--------------|------|------|
| 1 | auto-memory | ✅ | ✅ memory_create ×2 | ✅ | コーヒー好みと猫の事実を個別に記録 |
| 2 | recall-weaver | ✅ | ✅ memory_search ×2 | ✅ | 適切な検索クエリで複数回検索 |
| 3 | mood-sync | ✅ | ✅ update_context | ✅ | auto-memoryも自律的に併用 |
| 4 | goal-coach | ✅ | ✅ goal_manage | ✅ | 目標リスト取得後に適切に対応 |
| 5 | image-gen | ✅ | ✅ image_generate | ✅ | 単体テストで成功確認（一括実行時はNvidiaレート制限で偶発失敗） |

**合格率: 5/5 (100%)** — 全スキルが invoke_skill → 対象ツール呼出の自律的チェーンを達成。

### 教訓
1. **無料モデルは動的に消える**: OpenRouterの無料枠は永続的でない。ライブ確認が必須。
2. **temperature=0 が鍵**: 小規模モデルではツール呼び出しの決定論的動作に温度0が重要。
3. **プロンプトの命令形強化**: 「ツールを呼べ」「説明だけで済ませるな」が効果的。
4. **セッションIDの一意性**: テスト間でコンテキスト汚染を防ぐために必須。
5. **Nemotron 3 Ultra はツール呼び出しに優秀**: 55B activeにも関わらず自律的スキル呼出を安定して達成。
