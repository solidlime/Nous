"""Sudachi-based Japanese NER extractor — lightweight (~70MB) replacement for ja_ginza."""

from __future__ import annotations

import asyncio

from sudachipy import Dictionary as SudachiDict
from sudachipy.tokenizer import Tokenizer as SudachiTokenizer


class SudachiExtractor:
    """Sudachi morphological analyzer wrapper for named entity extraction.

    Uses Sudachi's part-of-speech tags to identify proper nouns (人名, 地名, 組織名).
    Lazy-loads the dictionary on first call.
    """

    # Top-level POS categories to consider
    _TARGET_POS = frozenset({"名詞"})

    def __init__(self) -> None:
        self._tokenizer: SudachiTokenizer | None = None  # lazy load

    def _ensure_loaded(self) -> None:
        if self._tokenizer is None:
            self._tokenizer = SudachiDict().create()

    def extract(self, text: str) -> list[dict]:
        """Extract named entities from *text*.

        Returns a list of dicts with keys ``name``, ``type``, ``start``, ``end``.
        """
        self._ensure_loaded()
        assert self._tokenizer is not None  # ensured above
        morphemes = self._tokenizer.tokenize(text)
        entities: list[dict] = []
        for m in morphemes:
            pos = m.part_of_speech()
            if not pos or pos[0] not in self._TARGET_POS:
                continue
            # Proper noun filter: second POS element must be "固有名詞"
            if len(pos) < 2 or pos[1] != "固有名詞":
                continue
            entity_type = self._classify(pos)
            entities.append(
                {
                    "name": m.surface(),
                    "type": entity_type,
                    "start": m.begin(),
                    "end": m.end(),
                }
            )
        return entities

    @staticmethod
    def _classify(pos: list[str]) -> str:
        """Map Sudachi POS subtype to entity type string."""
        if len(pos) >= 3:
            subtype = pos[2]
            if subtype in ("人名", "姓", "名"):
                return "person"
            if subtype in ("地名",):
                return "location"
            if subtype in ("組織",):
                return "organization"
        return "entity"


class HybridEntityExtractor:
    """Dual-path extractor: regex (fast) + Sudachi (accurate).

    Use ``extract_fast`` for real-time / inline usage and
    ``extract_accurate`` (async) for background enrichment tasks.
    """

    def __init__(self) -> None:
        from nous.domain.memory.entity_extractor import SimpleEntityExtractor

        self._fast = SimpleEntityExtractor()
        self._sudachi: SudachiExtractor | None = None

    def extract_fast(self, text: str) -> list[tuple[str, str]]:
        """Fast path: regex-based extraction for real-time use."""
        return self._fast.extract(text)

    async def extract_accurate(self, text: str) -> list[dict]:
        """Slow path: Sudachi NER for background tasks.

        Sudachi tokenization is CPU-bound so it is offloaded to a thread.
        """
        if self._sudachi is None:
            self._sudachi = SudachiExtractor()
        return await asyncio.to_thread(self._sudachi.extract, text)
