"""ONNX Runtime reranker using tokenizers + onnxruntime.

Replaces the old sentence-transformers CrossEncoder backend with a lighter
ONNX inference pipeline for search result re-ranking.
"""

from __future__ import annotations

import os
import threading

import numpy as np
import onnxruntime
from huggingface_hub import snapshot_download
from tokenizers import Tokenizer

from nous.infrastructure.logging.structured import get_logger

logger = get_logger(__name__)


class RerankerModel:
    """Lazy-loading reranker model for search result refinement.

    Uses ONNX Runtime + tokenizers instead of the old CrossEncoder backend.
    Thread-safe with double-checked locking.
    """

    def __init__(
        self,
        model_name: str = "hotchpotch/japanese-reranker-xsmall-v2",
        enabled: bool = True,
    ) -> None:
        self.model_name = model_name
        self.enabled = enabled
        self._session: onnxruntime.InferenceSession | None = None
        self._tokenizer: Tokenizer | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rerank(
        self,
        query: str,
        results: list[tuple[str, float]],
        contents: dict[str, str],
        top_k: int = 5,
    ) -> list[tuple[str, float]]:
        """Rerank results using a cross-encoder model.

        Args:
            query: The search query.
            results: List of (key, score) from initial search.
            contents: Mapping of key -> content for reranking.
            top_k: Number of results to return.

        Returns:
            Reranked list of (key, score).
        """
        if not self.enabled or not results:
            return results[:top_k]

        self._ensure_loaded()
        assert self._session is not None
        assert self._tokenizer is not None

        # Build query-document pairs for keys that have content available
        valid_entries: list[tuple[str, float]] = []
        pairs_text: list[tuple[str, str]] = []
        for key, original_score in results:
            if key in contents:
                pairs_text.append((query, contents[key]))
                valid_entries.append((key, original_score))

        if not pairs_text:
            return results[:top_k]

        try:
            # Encode all pairs with manual padding
            encodings = [self._tokenizer.encode(q, d) for q, d in pairs_text]
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
            logits = outputs[0]  # (batch, 1)

            # Sigmoid
            scores = 1.0 / (1.0 + np.exp(-logits[:, 0]))

        except Exception as e:
            logger.warning("Reranker prediction failed, returning original order: %s", e)
            return results[:top_k]

        # Combine reranker scores with original scores (weighted blend)
        combined: list[tuple[str, float]] = []
        for (key, original_score), rerank_score in zip(valid_entries, scores, strict=True):
            blended = float(rerank_score) * 0.7 + original_score * 0.3
            combined.append((key, blended))

        combined.sort(key=lambda x: x[1], reverse=True)
        return combined[:top_k]

    # ------------------------------------------------------------------
    # Model lifecycle
    # ------------------------------------------------------------------

    def reload_model(
        self,
        new_model_name: str | None = None,
        new_enabled: bool | None = None,
    ) -> dict:
        """Reload the model (thread-safe). Falls back to previous on failure."""
        with self._lock:
            old_session = self._session
            old_tokenizer = self._tokenizer
            old_name = self.model_name
            old_enabled = self.enabled

            if new_model_name:
                self.model_name = new_model_name
            if new_enabled is not None:
                self.enabled = new_enabled

            self._session = None
            self._tokenizer = None

            if not self.enabled:
                if old_session is not None:
                    del old_session
                if old_tokenizer is not None:
                    del old_tokenizer
                return {
                    "status": "disabled",
                    "model": self.model_name,
                    "message": "Reranker disabled",
                }

            try:
                self._load_model()
                if old_session is not None:
                    del old_session
                if old_tokenizer is not None:
                    del old_tokenizer
                return {
                    "status": "ready",
                    "model": self.model_name,
                    "message": f"Reranker reloaded: {self.model_name}",
                }
            except Exception as e:
                logger.error("Failed to reload reranker model: %s", e)
                self._session = old_session
                self._tokenizer = old_tokenizer
                self.model_name = old_name
                self.enabled = old_enabled
                return {
                    "status": "error",
                    "model": self.model_name,
                    "message": f"Reload failed, reverted: {e}",
                }

    def unload(self) -> None:
        """Release model resources."""
        with self._lock:
            self._session = None
            self._tokenizer = None
            logger.info("Reranker model unloaded: %s", self.model_name)

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
        """Download ONNX model + tokenizer, create InferenceSession (CPU)."""
        logger.info("Loading reranker model: %s", self.model_name)

        # 1. Download ONNX model
        model_dir = snapshot_download(self.model_name)
        onnx_path = os.path.join(model_dir, "onnx", "model.onnx")

        # 2. Load tokenizer (same repo as model for reranker)
        tok = Tokenizer.from_pretrained(self.model_name)
        tok.enable_padding(pad_id=3, pad_token="<pad>")
        tok.enable_truncation(max_length=512)
        self._tokenizer = tok

        # 3. Create ONNX session (CPU only)
        sess_options = onnxruntime.SessionOptions()
        sess_options.intra_op_num_threads = min(4, os.cpu_count() or 4)
        self._session = onnxruntime.InferenceSession(
            onnx_path,
            providers=["CPUExecutionProvider"],
            sess_options=sess_options,
        )

        logger.info("Reranker model loaded: %s", self.model_name)
