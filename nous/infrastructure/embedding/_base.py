"""Base class for ONNX Runtime models with lazy-loading via double-checked locking.

Shared by EmbeddingModel and RerankerModel to eliminate the identical
``_ensure_loaded()`` / ``_lock`` / ``_session`` pattern duplication.
"""

from __future__ import annotations

import logging
import os
import threading
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import onnxruntime

logger = logging.getLogger(__name__)


def _hf_revision(env_var: str) -> str | None:
    """Pinned HuggingFace revision from env (None = latest, current behavior).

    Lets operators pin ``snapshot_download`` without code changes, e.g.
    ``NOUS_EMBEDDING__REVISION=<sha>``.
    """
    return os.environ.get(env_var) or None


class OnnxBaseModel(ABC):
    """Lazy-loading ONNX model with thread-safe double-checked locking.

    Subclasses must implement :meth:`_load_model` to download the model
    and create the :attr:`_session`.
    """

    def __init__(self) -> None:
        self._session: onnxruntime.InferenceSession | None = None
        self._lock = threading.Lock()
        self._bg_load_started = False

    @property
    def is_loaded(self) -> bool:
        """Whether the model session has been created (no load triggered)."""
        return self._session is not None

    def ensure_loaded_background(self) -> None:
        """Start at most one background load thread; never blocks.

        Used by request paths that prefer graceful degradation over a
        multi-second cold load (snapshot_download + ONNX session creation).
        Self-healing: once the thread finishes (success or failure), a later
        call may start a fresh attempt.
        """
        with self._lock:
            if self._session is not None or self._bg_load_started:
                return
            self._bg_load_started = True
        threading.Thread(target=self._load_worker, daemon=True).start()

    def _load_worker(self) -> None:
        try:
            self._ensure_loaded()
        except Exception:
            logger.warning("Background model load failed (will retry on next request)", exc_info=True)
        finally:
            with self._lock:
                self._bg_load_started = False

    def _ensure_loaded(self) -> None:
        """Lazy-load model with double-checked locking."""
        if self._session is None:
            with self._lock:
                if self._session is None:
                    self._load_model()

    @abstractmethod
    def _load_model(self) -> None:
        """Download ONNX model + tokenizer and create InferenceSession."""
        ...
