"""脳側 LLM の呼び出しパラメータ解決。

旧・内省エンジン (E2) の残骸。自発的内省・独り言・好奇心探索は
2026-11-08（kanban #32）以降トリガを持たず、2026-11-09（kanban #35）で
丸ごと削除した。残っているのは矛盾判定 (MemoryEnricher) が共有する
パラメータ解決鎖だけで、use_cases._init_brain_llm がここから import する。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nous.domain.provider_config import REASONING_BUDGETS

if TYPE_CHECKING:
    from nous.domain.chat_config import ChatConfig


@dataclass(frozen=True)
class BrainLLMParams:
    """脳側LLM呼び出しパラメータ。None は「呼び出し先の既定を使え」の意味。"""

    max_tokens: int | None
    temperature: float | None
    reasoning_effort: str | None


def _as_int(value, default: int = 0) -> int:
    """LLM 設定値の安全な int 化。不正値は default（_resolve_brain_llm_params 専用の防御）。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _resolve_brain_llm_params(config: ChatConfig | None) -> BrainLLMParams:
    """脳側 LLM 呼び出しパラメータの単一解決点。

    - brain_max_tokens > 0 は全モードで明示上書き
    - brain_llm_dedicated OFF → 会話用 provider_config に従う（max_tokens/temperature/reasoning）
    - ON / cfg None → 呼び出し先既定
    - brain_reasoning_enabled: None=解決済みLLM設定に従う / True=brain_reasoning_effort 強制 / False=推論なし
    - reasoning 有効（effort 非None）時は max_tokens を floor=max(4096, budget+1024) まで嵩上げ。
      session_config の保存時昇格と同一式で、openai_compat の非Anthropic互換経路（嵩上げなし）も守る。
    """
    if config is None:
        return BrainLLMParams(max_tokens=None, temperature=None, reasoning_effort=None)
    p = config.provider_config
    explicit_tokens = _as_int(getattr(config, "brain_max_tokens", 0))
    dedicated = bool(getattr(config, "brain_llm_dedicated", False))
    max_tokens: int | None
    if explicit_tokens > 0:
        max_tokens = explicit_tokens
    elif dedicated:
        max_tokens = None
    else:
        max_tokens = _as_int(getattr(p, "max_tokens", 0)) or None
    temperature: float | None = None
    if not dedicated:
        try:
            # falsy チェックを外す: 会話側の明示 temperature=0.0 を 0.7 に化けさせない。
            # 不正値（None / 非数値文字列）は TypeError/ValueError で 0.7 へ落ちる。
            temperature = float(getattr(p, "temperature", 0.7))
        except (TypeError, ValueError):
            temperature = 0.7
    r_flag = getattr(config, "brain_reasoning_enabled", None)
    if r_flag is None:
        # None（継承）: 専用OFFなら会話用 reasoning 設定に従う、ON なら脳側既定（なし）。
        follow_chat = not dedicated and getattr(p, "reasoning_enabled", False)
        effort: str | None = str(getattr(p, "reasoning_effort", "medium") or "medium") if follow_chat else None
    elif r_flag:
        effort = str(getattr(config, "brain_reasoning_effort", "medium") or "medium")
    else:
        effort = None  # False（推論なし）強制
    if effort is not None:
        # 推論が実際に有効なら、推論分（budget）を賄える max_tokens 下限を保証する。
        # 専用LLM ON × brain_max_tokens=0（継承）が enricher ctor 既定 512 に落ちて
        # 推論だけで budget を食い潰す穴を塞ぐ（session_config は 0 を生で保存するため
        # 保存時昇格では補えない）。budget 不明の effort は floor 4096 のみ。
        budget = REASONING_BUDGETS.get(effort)
        floor = max(4096, budget + 1024) if budget is not None else 4096
        max_tokens = max(max_tokens or 0, floor)
    return BrainLLMParams(max_tokens=max_tokens, temperature=temperature, reasoning_effort=effort)


def _resolve_llm_config(config: ChatConfig | None, settings) -> tuple[str, str, str, str]:
    """(provider, api_key, model, base_url)。ブレイン解決鎖の旧経路。

    shortcut: 現在の呼び出し元はゼロ（use_cases は同じ鎖を _init_brain_llm 内に
    直書きしている）。kanban #35 の指示で残置。次の掃除で消してよい。
    """
    if config is None:
        me = settings.memory_enrichment
        return me.provider, me.get_effective_api_key(settings), me.model, me.base_url
    if not config.brain_llm_dedicated:
        p = config.provider_config
        return p.provider, p.get_effective_api_key(), p.get_effective_model(), p.get_effective_base_url()
    me = settings.memory_enrichment
    provider = config.brain_llm_provider or me.provider
    model = config.brain_llm_model or me.model
    base_url = config.brain_llm_base_url or me.base_url
    api_key = config.brain_llm_api_key or me.get_effective_api_key(settings)
    if not api_key and provider == config.provider_config.provider:
        api_key = config.provider_config.get_effective_api_key()
    return provider, api_key, model, base_url
