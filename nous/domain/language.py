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
        from langdetect import DetectorFactory
        from langdetect import detect as _detect

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
