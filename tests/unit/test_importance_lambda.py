"""Importance-scaled decay exponent (F1/T1) tests.

- 高 importance ほど減衰が遅い
- k=0 で現行（base 指数そのまま）と一致
- λ_eff は非負（clamp）
- access_count/last_accessed は強度計算に入らない（監査メタデータ専用）
"""

from __future__ import annotations

import inspect
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from nous.application.workers.decay_worker import DecayWorker
from nous.domain.memory.entities import (
    Memory,
    MemoryStrength,
    importance_scaled_exponent,
)
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now

BASE_STM = 0.5
ELAPSED_H = 24.0


def _strength(key: str) -> MemoryStrength:
    s = MemoryStrength(memory_key=key)
    s.last_decay = get_now() - timedelta(hours=ELAPSED_H)
    s.stability = 1.0
    return s


def _memory(key: str, importance: float) -> Memory:
    now = get_now()
    return Memory(key=key, content="テスト用の記憶内容です。", created_at=now, updated_at=now, importance=importance)


def _ctx(strengths: list[MemoryStrength], memories: list[Memory], min_strength: float = 0.0) -> MagicMock:
    ctx = MagicMock()
    ctx.memory_repo.get_all_strengths.return_value = Success(strengths)
    ctx.memory_repo.find_all.return_value = Success(memories)
    ctx.memory_repo.save_strength.return_value = Success(None)
    ctx.settings.forgetting.min_strength = min_strength
    return ctx


def _saved_strengths(ctx: MagicMock) -> dict[str, float]:
    return {c.args[0].memory_key: c.args[0].strength for c in ctx.memory_repo.save_strength.call_args_list}


class TestImportanceLambda:
    def test_higher_importance_decays_slower(self) -> None:
        """高 importance → 小さい λ_eff → 高い recall"""
        eff_hi = importance_scaled_exponent(BASE_STM, 0.9)
        eff_lo = importance_scaled_exponent(BASE_STM, 0.1)
        assert eff_hi < eff_lo
        assert MemoryStrength(memory_key="x").compute_recall(ELAPSED_H, eff_hi) > MemoryStrength(
            memory_key="x"
        ).compute_recall(ELAPSED_H, eff_lo)

    def test_decay_cycle_higher_importance_keeps_more_strength(self) -> None:
        """_decay_cycle 実経路でも高 importance が強く残る"""
        ctx = _ctx([_strength("hi"), _strength("lo")], [_memory("hi", 0.9), _memory("lo", 0.1)])
        DecayWorker(ctx, interval_seconds=3600)._decay_cycle()
        saved = _saved_strengths(ctx)
        assert saved["hi"] > saved["lo"]

    def test_k_zero_matches_baseline(self) -> None:
        """k=0 → λ_eff == base（現行動作と一致）"""
        assert importance_scaled_exponent(BASE_STM, 0.9, k=0.0) == BASE_STM
        assert importance_scaled_exponent(0.3, 0.1, k=0.0) == 0.3

        cfg = MagicMock()
        cfg.forgetting_min_strength = 0.0
        cfg.importance_lambda_k = 0
        ctx = _ctx([_strength("hi"), _strength("lo")], [_memory("hi", 0.9), _memory("lo", 0.1)])
        DecayWorker(ctx, interval_seconds=3600, config=cfg)._decay_cycle()
        saved = _saved_strengths(ctx)
        score_hi = MemoryStrength(memory_key="h").compute_strength_score(importance=0.9)
        score_lo = MemoryStrength(memory_key="h").compute_strength_score(importance=0.1)
        # recall 因子が両者で等しい（= base 指数の R）
        assert saved["hi"] / score_hi == pytest.approx(saved["lo"] / score_lo)

    def test_lambda_eff_non_negative(self) -> None:
        """λ_eff は clamp で非負・上は base 止まり"""
        assert importance_scaled_exponent(BASE_STM, 1.0, k=2.0) == 0.0
        assert importance_scaled_exponent(BASE_STM, 0.0) == BASE_STM
        assert importance_scaled_exponent(0.3, 1.0, k=0.5) == pytest.approx(0.15)

    def test_access_count_not_double_counted(self) -> None:
        """access_count/last_accessed は強度計算の入力に使わない"""
        sig = inspect.signature(MemoryStrength.compute_strength_score)
        assert "access_count" not in sig.parameters
        assert "last_accessed" not in sig.parameters
