# ADR-001: 中央言語設定の導入

## Status
Proposed

## Date
2026-07-20

## Context

### 問題
Nous プロジェクトの LLM 出力言語がコンポーネント間で一貫せず、英語/日本語/中国語が混在している。

| コンポーネント | ファイル | 現状 | 問題 |
|--------------|---------|------|------|
| ReflectionEngine | `reflection.py` | `"Generate insights in {persona}'s natural language."` | LLM任せ、言語が安定しない |
| レガシー maybe_run_reflection | `reflection.py` | 英語プロンプト + `SearchQuery("記憶 事実 出来事")`（日本語） | 和英混在 |
| SessionSummarizer | `summarizer.py` | `"日本語で簡潔に要約"` 固定 | 日本語以外に対応不可 |
| CompressStep (LLM要約) | `compress.py` | `"300文字以内の日本語でまとめて"` 固定 | 同上 |
| CompressStep (trim) | `compress.py` | `"関連記憶"` の文字列検索 | 非日本語システムプロンプトで動作不能 |
| MemoryLLM | `memory_llm.py` | プロンプト全体が日本語 | 同上 |
| System Prompt | `prompt.py` | `TOOL_USAGE_GUIDELINES` が日本語固定 | 同上 |
| スキル定義 | `data/skills/*/SKILL.md` | 全スキル日本語 | 同上 |
| フロントエンド HTML | `base.py`, `persona.py` | `<html lang="ja">` 固定 | 同上 |
| ChatConfig | `chat_config.py` | `language` フィールド不在 | 設定手段なし |

### 制約
1. **コード変更量の現実性**: 全ファイル書き換えは避ける
2. **後方互換**: 既存ユーザー（日本語前提）の動作を破壊しない
3. **シンプルさ**: 過剰設計を避ける

## Decision

### 1. 言語設定の置き場所: `ChatConfig.language` (per-persona)

```python
class ChatConfig(BaseModel):
    # ... existing fields ...
    language: str = "ja"  # "ja" | "en" | "zh" | "auto" | etc.
```

**選択理由**:
- `ChatConfig` は既に persona 単位で永続化されている → 新たな設定ストア不要
- per-persona により、異なるペルソナで異なる言語を設定可能（マルチリンガルユースケース）
- 将来的にグローバルユーザー設定を追加する場合も、`ChatConfig.language` を override する形でレイヤー可能

**デフォルト値: `"ja"`**:
- 既存ユーザー（日本語前提）の後方互換を保証
- `"auto"` は明示的なオプトイン

### 2. 自動検出の仕組み: `langdetect` + セッション初回メッセージ

```python
# nous/domain/language.py (新規)
from langdetect import detect as _detect, DetectorFactory

DetectorFactory.seed = 0  # 決定論的検出

def detect_language(text: str) -> str | None:
    """ユーザーメッセージから主要言語を検出。信頼度低の場合は None。"""
    try:
        result = _detect(text)
        return result  # "ja", "en", "zh-cn", etc.
    except Exception:
        return None
```

**検出タイミング**: セッション最初のユーザーメッセージ到着時、1回のみ実行

**選択理由**:
- `langdetect` は純粋 Python（依存ゼロ、〜1MB）、5ms 未満で検出完了
- LLM を使う場合のレイテンシ・コスト・プロバイダ依存を回避
- コード混じりでも主要言語を安定検出（Google の言語検出ライブラリベース）

### 3. プロンプトへの伝播: System Prompt 注入 + テンプレート変数（二段構え）

**3a. System Prompt 注入（メインチャット出力用）**:
```python
# prompt.py PromptBuildStep.run() の先頭付近に追加
lang = LanguageResolver(config).resolve(user_message=turn_ctx.user_message)
parts.insert(0, f"[System Directive] Always respond in {lang}. All output must be in {lang}.")
```

**3b. テンプレート変数（LLM操作プロンプト用）**:
各プロンプトテンプレートから言語固有文字列を削除し、`{language}` プレースホルダに置換:

```python
# summarizer.py: 変更前
_SUMMARIZE_PROMPT = """以下の会話を2〜3文の日本語で簡潔に要約してください。..."""

# summarizer.py: 変更後
_SUMMARIZE_PROMPT = """Summarize the following conversation in 2-3 sentences in {language}.
..."""
```

**選択理由**:
- System Prompt 注入は1行変更で全LLM出力をカバー（最小変更）
- テンプレート変数は要約・圧縮・リフレクションなど、特定のフォーマット指示が必要な箇所をカバー
- 二段構えにより、片方が効かなくてももう片方がカバーする冗長性

### 4. `LanguageResolver` の導入

```python
# nous/domain/language.py (新規)

class LanguageResolver:
    """language 設定値 → 実際の言語コードへの解決を行う。
    
    優先順位:
      1. ChatConfig.language が "auto" 以外 → その値
      2. "auto" かつ detect_language() 成功 → 検出値
      3. それ以外 → "ja"（デフォルト）
    """
    def __init__(self, config: ChatConfig): ...
    def resolve(self, user_message: str | None = None) -> str: ...
    def display_name(self, code: str) -> str: ...  # "ja" → "日本語"
```

### 5. 対象範囲の決定

| コンポーネント | 対応 | 方法 | 優先度 |
|--------------|------|------|-------|
| System Prompt | ✅ | 注入 | P0 |
| Summarizer | ✅ | テンプレート変数 | P0 |
| Compress (LLM要約) | ✅ | テンプレート変数 | P0 |
| MemoryLLM | ✅ | テンプレート変数 + 先頭指示 | P0 |
| ReflectionEngine | ✅ | テンプレート変数 | P1 |
| legacy maybe_run_reflection | ✅ | テンプレート変数 | P1 |
| Skills (SKILL.md) | ❌ | 変更不要 | — |
| Frontend HTML `<html lang>` | ✅ | Accept-Language / ChatConfig反映 | P2 |
| Compress (_trim_system_prompt 文字列検索) | ⚠️ | 後続ADRで対応 | P2 |
| 音声認識 lang | ✅ | ChatConfig.language 連動 | P2 |

**スキル定義を変更しない理由**:
スキル定義は LLM への内部指示（HOW to operate）であり、出力言語（WHAT language to output）とは独立した関心事。System Prompt 注入で出力言語を制御するため、スキル定義の翻訳は不要。

### 6. フロントエンド連携

- `ChatConfig` 設定パネルに言語選択ドロップダウンを追加（`ja`/`en`/`zh`/`auto`）
- 初回訪問時、`Accept-Language` ヘッダを初期値として使用
- `settings.py` + `chat-settings.js` に各1項目追加

## Alternatives Considered

### A. ユーザー単位のグローバル設定
- **Pros**: 全ペルソナで一貫した言語設定
- **Cons**: 新たな設定ストア・API が必要、ChatConfig との整合性管理が複雑化
- **Rejected**: 最小変更の原則に反する。per-persona で十分であり、将来的にグローバル設定のレイヤー追加は可能

### B. LLM に言語検出させる
- **Pros**: 混合言語・コード混じりで高精度
- **Cons**: レイテンシ増加（500ms+）、コスト（API呼び出し）、プロバイダ依存
- **Rejected**: 言語検出に LLM を呼ぶのは過剰。`langdetect` で95%ケースをカバー可能

### C. 全スキル定義の多言語化
- **Pros**: 完全な多言語対応
- **Cons**: メンテナンス負荷が爆発（変更のたびにN言語翻訳）、一貫性リスク
- **Rejected**: スキルは内部指示であり、出力言語とは分離可能

### D. System Prompt 注入のみ（テンプレート変数なし）
- **Pros**: 最小変更（1行）
- **Cons**: LLM が要約プロンプトのフォーマット指示（例: "300文字以内"）を上書きできない
- **Rejected**: 冗長性の欠如。要約などの構造化出力では明示的な言語指示が必要

## Consequences

### Positive
- 全 LLM 出力の言語が一貫する
- 1つの設定値変更で全コンポーネントに伝播
- 既存ユーザーにはゼロインパクト（デフォルト "ja"）
- `langdetect` 依存のみ（純粋 Python、軽量）

### Negative
- `langdetect` が新規依存として追加される（〜1MB）
- テンプレート文字列が英語化される（日本語ネイティブ開発者の可読性低下）
- `_trim_system_prompt` の日本語文字列検索問題は未解決（P2 で後続対応）

### Risks
| リスク | 深刻度 | 緩和策 |
|-------|--------|-------|
| `langdetect` が短い/コード混じりメッセージを誤検出 | Low | デフォルト "ja" へのフォールバック |
| 全テンプレート英語化による開発者の心理的抵抗 | Low | プロンプトテンプレートの言語は出力言語と独立。P1 で段階移行 |
| スキルが日本語であることが LLM の出力言語に影響 | Low | System Prompt 注入の "Always respond in {language}" が上書き |
| CompressStep の `"関連記憶"` 検索が非日本語プロンプトで失敗 | Medium | P2 で locale-agnostic なセクションマーカーに変更予定 |

## Migration Plan

### Phase 1 (P0, ~150 LOC)
1. `ChatConfig` に `language: str = "ja"` を追加
2. `nous/domain/language.py` を新規作成（`LanguageResolver`, `detect_language`）
3. `prompt.py`: System Prompt 先頭に言語指示を注入
4. `summarizer.py`: `_SUMMARIZE_PROMPT` を `{language}` テンプレート化
5. `compress.py`: `SUMMARIZE_PROMPT` を `{language}` テンプレート化
6. `memory_llm.py`: `_MEMORY_LLM_PROMPT` の先頭に言語指示行を追加

### Phase 2 (P1, ~100 LOC)
7. `reflection.py`: `_REFLECTION_PROMPT` と `ReflectionEngine._build_system_message()` をテンプレート化
8. `reflection.py`: legacy `maybe_run_reflection` の `SearchQuery` 日本語文字列を修正

### Phase 3 (P2, ~100 LOC)
9. フロントエンド設定パネルに言語ドロップダウン追加
10. `Accept-Language` ヘッダ連携
11. 音声認識 `lang` 連動
12. `_trim_system_prompt` の locale-agnostic 対応（後続 ADR）

## Verification

- [ ] 全テストが通過すること（`python -m pytest tests/ -x -q`）
- [ ] `language="ja"` で既存動作が変わらないこと
- [ ] `language="en"` で全 LLM 出力が英語になること
- [ ] `language="auto"` で英語メッセージに対し英語出力になること
- [ ] `language="auto"` で日本語メッセージに対し日本語出力になること
- [ ] フロントエンド設定画面に言語選択が表示され、保存が反映されること
