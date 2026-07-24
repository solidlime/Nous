"""Base class for ONNX Runtime models with lazy-loading via double-checked locking.

Shared by EmbeddingModel and RerankerModel to eliminate the identical
``_ensure_loaded()`` / ``_lock`` / ``_session`` pattern duplication.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod

import onnxruntime


class OnnxBaseModel(ABC):
    """Lazy-loading ONNX model with thread-safe double-checked locking.

    Subclasses must implement :meth:`_load_model` to download the model
    and create the :attr:`_session`.
    """

    def __init__(self) -> None:
        self._session: onnxruntime.InferenceSession | None = None
        self._lock = threading.Lock()

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
