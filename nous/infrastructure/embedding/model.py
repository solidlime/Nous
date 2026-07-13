"""ONNX Runtime embedding model using tokenizers + onnxruntime.

Replaces the old sentence-transformers backend with a lighter ONNX inference
pipeline.  Lazy-loaded with double-checked locking; supports sync and async
encode interfaces with query/document prefixing.
"""

from __future__ import annotations

import asyncio
import os
import threading

import numpy as np
import onnxruntime
from huggingface_hub import snapshot_download
from tokenizers import Tokenizer

from nous.config.settings import EmbeddingConfig
from nous.infrastructure.logging.structured import get_logger

logger = get_logger(__name__)

_QUERY_PREFIX = "検索クエリ: "
_DOCUMENT_PREFIX = "検索文書: "


class EmbeddingModel:
    """Lazy-loading embedding model backed by ONNX Runtime + tokenizers.

    Thread-safe (double-checked locking).  Provides sync and async encode
    methods that return L2-normalised embeddings via mean pooling.

    Public API is stable — do not change.
    """

    def __init__(
        self,
        config: EmbeddingConfig | None = None,
    ) -> None:
        self.config = config or EmbeddingConfig()
        self._session: onnxruntime.InferenceSession | None = None
        self._tokenizer: Tokenizer | None = None
        self._dimension: int | None = None
        self._lock = threading.Lock()
        self._tok_name: str = "cl-nagoya/ruri-v3-30m"

    # ------------------------------------------------------------------
    # Public sync API
    # ------------------------------------------------------------------

    @property
    def dimension(self) -> int:
        """Return embedding dimension, loading the model if needed."""
        if self._dimension is None:
            self._ensure_loaded()
        assert self._dimension is not None
        return self._dimension

    def encode(self, text: str, *, is_query: bool = False) -> np.ndarray:
        """Encode a single text to a normalised vector (1D)."""
        self._ensure_loaded()
        assert self._session is not None
        assert self._tokenizer is not None

        prefix = _QUERY_PREFIX if is_query else _DOCUMENT_PREFIX
        prefixed = f"{prefix}{text}"

        encoded = self._tokenizer.encode(prefixed)
        input_ids = np.array([encoded.ids], dtype=np.int64)
        attention_mask = np.array([encoded.attention_mask], dtype=np.int64)

        outputs = self._session.run(
            None,
            {"input_ids": input_ids, "attention_mask": attention_mask},
        )
        hidden = outputs[0]  # (1, seq_len, dim)

        emb = self._pool(hidden, attention_mask)  # (1, dim)
        return emb[0]  # 1D

    def encode_batch(
        self,
        texts: list[str],
        *,
        is_query: bool = False,
    ) -> np.ndarray:
        """Encode multiple texts to normalised vectors (2D).

        Splits input into chunks of ``self.config.batch_size`` to limit
        memory usage during ONNX inference.
        """
        self._ensure_loaded()
        assert self._session is not None
        assert self._tokenizer is not None

        results: list[np.ndarray] = []
        bs = self.config.batch_size
        for start in range(0, len(texts), bs):
            chunk = texts[start : start + bs]
            emb = self._encode_batch_internal(chunk, is_query=is_query)
            results.append(emb)

        return np.vstack(results) if results else np.empty((0, self.dimension), dtype=np.float64)

    def _encode_batch_internal(
        self,
        texts: list[str],
        *,
        is_query: bool = False,
    ) -> np.ndarray:
        """Encode a single chunk of texts (no chunking)."""
        prefix = _QUERY_PREFIX if is_query else _DOCUMENT_PREFIX
        prefixed = [f"{prefix}{t}" for t in texts]

        # Encode all texts, find max length for padding
        encodings = [self._tokenizer.encode(t) for t in prefixed]
        max_len = max(len(e.ids) for e in encodings) if encodings else 0
        max_len = min(max_len, 512)

        batch_ids = np.zeros((len(encodings), max_len), dtype=np.int64)
        batch_mask = np.zeros((len(encodings), max_len), dtype=np.int64)

        for i, enc in enumerate(encodings):
            length = min(len(enc.ids), max_len)
            batch_ids[i, :length] = np.array(enc.ids[:length], dtype=np.int64)
            batch_mask[i, :length] = np.array(enc.attention_mask[:length], dtype=np.int64)

        outputs = self._session.run(
            None,
            {"input_ids": batch_ids, "attention_mask": batch_mask},
        )
        hidden = outputs[0]  # (batch, seq_len, dim)

        return self._pool(hidden, batch_mask)  # (batch, dim)

    # ------------------------------------------------------------------
    # Public async API — delegates to sync via asyncio.to_thread
    # ------------------------------------------------------------------

    async def async_encode(self, text: str, *, is_query: bool = False) -> np.ndarray:
        """Async version of :meth:`encode`."""
        return await asyncio.to_thread(self.encode, text, is_query=is_query)

    async def async_encode_batch(
        self,
        texts: list[str],
        *,
        is_query: bool = False,
    ) -> np.ndarray:
        """Async version of :meth:`encode_batch`."""
        return await asyncio.to_thread(self.encode_batch, texts, is_query=is_query)

    async def async_dimension(self) -> int:
        """Async version of :attr:`dimension`."""
        return await asyncio.to_thread(lambda: self.dimension)

    # ------------------------------------------------------------------
    # Model lifecycle
    # ------------------------------------------------------------------

    def reload_model(
        self,
        new_model_name: str | None = None,
        new_device: str | None = None,
    ) -> dict:
        """Reload the model (thread-safe). Falls back to previous on failure."""
        with self._lock:
            old_session = self._session
            old_tokenizer = self._tokenizer
            old_dimension = self._dimension
            old_name = self.config.model
            old_device = self.config.device

            if new_model_name:
                self.config.model = new_model_name
            if new_device:
                self.config.device = new_device

            self._session = None
            self._tokenizer = None
            self._dimension = None

            try:
                self._load_model()
                if old_session is not None:
                    del old_session
                if old_tokenizer is not None:
                    del old_tokenizer
                return {
                    "status": "ready",
                    "model": self.config.model,
                    "dimension": self._dimension,
                    "message": f"Model reloaded: {self.config.model}",
                }
            except Exception as e:
                logger.error("Failed to reload embedding model: %s", e)
                self._session = old_session
                self._tokenizer = old_tokenizer
                self._dimension = old_dimension
                self.config.model = old_name
                self.config.device = old_device
                return {
                    "status": "error",
                    "model": self.config.model,
                    "dimension": self._dimension,
                    "message": f"Reload failed, reverted: {e}",
                }

    def unload(self) -> None:
        """Release model resources."""
        with self._lock:
            self._session = None
            self._tokenizer = None
            self._dimension = None
            logger.info("Embedding model unloaded: %s", self.config.model)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Lazy-load model with double-checked locking."""
        if self._session is None:
            with self._lock:
                if self._session is None:
                    self._load_model()

    def _load_model(self) -> None:
        """Download ONNX model + tokenizer, create InferenceSession."""
        logger.info("Loading embedding model: %s (device=%s)", self.config.model, self.config.device)

        # 1. Download ONNX model
        model_dir = snapshot_download(self.config.model)
        onnx_path = os.path.join(model_dir, "onnx", "model.onnx")

        # 2. Load tokenizer
        tok = Tokenizer.from_pretrained(self._tok_name)
        tok.enable_padding(pad_id=3, pad_token="<pad>")
        tok.enable_truncation(max_length=512)
        self._tokenizer = tok

        # 3. Create ONNX session
        sess_options = onnxruntime.SessionOptions()
        sess_options.intra_op_num_threads = min(4, os.cpu_count() or 4)
        providers = self._get_providers()
        self._session = onnxruntime.InferenceSession(
            onnx_path,
            providers=providers,
            sess_options=sess_options,
        )

        # 4. Detect dimension from output shape
        self._dimension = self._session.get_outputs()[0].shape[2]
        logger.info(
            "Embedding model loaded: dim=%d, model=%s",
            self._dimension,
            self.config.model,
        )

    def _get_providers(self) -> list[str]:
        """Return ONNX Runtime provider list based on device."""
        if self.config.device == "cpu":
            return ["CPUExecutionProvider"]
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]

    def _pool(self, hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """Mean pooling with attention mask, then L2 normalise.

        Args:
            hidden: (batch, seq_len, dim) — raw hidden states.
            mask:   (batch, seq_len) — attention mask (int64).

        Returns:
            (batch, dim) — pooled and normalised embeddings.
        """
        # Expand mask to 3D
        mask_3d = mask.astype(hidden.dtype)[..., np.newaxis]  # (batch, seq_len, 1)

        masked = hidden * mask_3d
        summed = masked.sum(axis=1)  # (batch, dim)
        counts = mask_3d.sum(axis=1).clip(min=1e-9)  # (batch, 1)

        pooled = summed / counts  # (batch, dim)

        # L2 normalise
        norms = np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
        return pooled / norms
