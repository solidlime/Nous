"""感情減衰計算 — recency decay for memory scoring and emotion/body decay coordination.

実装は ``nous.domain.shared.time_utils`` へ一元化した。既存 import 元
（prepare.py / test_chat_pipeline.py / test_generative_retrieval.py 等）を
壊さないよう、本モジュールは re-export のみを担う。
"""

from __future__ import annotations

from nous.domain.shared.time_utils import RECENCY_LAMBDA as _RECENCY_LAMBDA
from nous.domain.shared.time_utils import compute_recency_decay as _compute_recency_decay

__all__ = ["_RECENCY_LAMBDA", "_compute_recency_decay"]
