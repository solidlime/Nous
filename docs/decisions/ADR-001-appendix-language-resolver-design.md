# ADR-001 Appendix: LanguageResolver 設計詳細

## モジュール構成

```
nous/domain/language.py          # 新規: LanguageResolver + detect_language()
```

## インターフェース設計

```python
"""言語設定の解決と自動検出。

中央の言語設定 ChatConfig.language を各コンポーネントのプロンプトに
注入するための言語解決ロジック。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.domain.chat_config import ChatConfig

# サポートする言語コード → 表示名
SUPPORTED_LANGUAGES: dict[str, str] = {
    "ja": "日本語",
    "en": "English",
    "zh": "中文",
    "ko": "한국어",
    "auto": "自動検出",
}

# "auto" 検出時のデフォルト
FALLBACK_LANGUAGE = "ja"


def detect_language(text: str) -> str | None:
    """langdetect でテキストの主要言語を検出。

    Args:
        text: 検出対象テキスト（最低10文字推奨）

    Returns:
        言語コード（"ja", "en" など）または検出失敗時 None
    """
    if len(text.strip()) < 5:
        return None

    try:
        from langdetect import detect as _detect, DetectorFactory
        DetectorFactory.seed = 0
        return _detect(text)
    except Exception:
        return None


class LanguageResolver:
    """ChatConfig.language を実際の言語コードに解決する。

    解決順序:
      1. config.language が SUPPORTED_LANGUAGES の明示的キー → その値
      2. config.language == "auto" → detect_language(user_message)
      3. 検出失敗または未設定 → FALLBACK_LANGUAGE ("ja")

    Usage:
        resolver = LanguageResolver(config)
        lang = resolver.resolve(user_message="こんにちは")
        prompt = f"Respond in {lang}."  # "ja"
    """

    def __init__(self, config: ChatConfig) -> None:
        self._config = config

    def resolve(self, user_message: str | None = None) -> str:
        """言語コードを解決する。

        Args:
            user_message: "auto" モード時の検出対象テキスト。
                          None の場合は FALLBACK_LANGUAGE を返す。
        """
        lang = getattr(self._config, "language", FALLBACK_LANGUAGE) or FALLBACK_LANGUAGE

        if lang == "auto":
            if user_message:
                detected = detect_language(user_message)
                if detected and detected in SUPPORTED_LANGUAGES:
                    return detected
            return FALLBACK_LANGUAGE

        if lang in SUPPORTED_LANGUAGES:
            return lang

        return FALLBACK_LANGUAGE

    @staticmethod
    def display_name(code: str) -> str:
        """言語コード → 表示名（UI用）"""
        return SUPPORTED_LANGUAGES.get(code, code)
```

## 呼び出しパターン

### パターン A: System Prompt 注入（prompt.py）

```python
# PromptBuildStep.run() 内
from nous.domain.language import LanguageResolver

resolver = LanguageResolver(config)
lang = resolver.resolve(user_message=turn_ctx.latest_user_message)
lang_directive = f"[System Directive] Always respond in {lang}. All output must be in {lang}."
parts.insert(1, lang_directive)  # TIME_CONTEXT の直後
```

### パターン B: テンプレート変数（summarizer.py, compress.py, memory_llm.py, reflection.py）

```python
# 各関数の呼び出し側で解決
resolver = LanguageResolver(config)
lang = resolver.resolve(user_message=user_msg)

prompt = _SUMMARIZE_PROMPT.format(
    language=LanguageResolver.display_name(lang),
    conversation=conversation_text,
)
```

### パターン C: MemoryLLM（特殊ケース）

`_MEMORY_LLM_PROMPT` は95行の構造化プロンプト。全体をテンプレート化する代わりに、先頭に1行追加:

```python
_MEMORY_LLM_PROMPT = """\
[System Directive] All output content must be written in {language}.

あなたは {persona_name} です。
...（以下、既存の日本語プロンプトを維持）...
"""
```

## プロンプトテンプレート変更例

### summarizer.py

```python
# 変更前
_SUMMARIZE_PROMPT = """\
以下の会話を2〜3文の日本語で簡潔に要約してください。
重要な情報・決定事項・感情的な出来事を優先してください。

【会話】
{conversation}

【出力】
要約文のみ。JSON不要。
"""

# 変更後
_SUMMARIZE_PROMPT = """\
Summarize the following conversation in 2-3 sentences in {language}.
Prioritize important information, decisions, and emotional events.

[Conversation]
{conversation}

[Output]
Summary only. No JSON.
"""
```

### compress.py

```python
# 変更前
SUMMARIZE_PROMPT = """以下の会話履歴を要約してください。重要な情報（ユーザーの発言、決定事項、好み、約束、感情的な出来事）を優先的に抽出し、300文字以内の日本語でまとめてください。
..."""

# 変更後
SUMMARIZE_PROMPT = """Summarize the conversation history below, in {language}.
Prioritize: user statements, decisions, preferences, promises, emotional events.
Keep the summary within approximately 300 characters.
..."""
```

### reflection.py (ReflectionEngine)

```python
# _build_system_message() 内の変更
# 変更前
f"Generate insights in {persona}'s natural language. "

# 変更後
f"Generate insights in {language}. "
```
