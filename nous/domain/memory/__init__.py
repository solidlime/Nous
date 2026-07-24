from __future__ import annotations

from nous.domain.memory.entities import Memory, MemoryStrength
from nous.domain.memory.entity_extractor import SimpleEntityExtractor
from nous.domain.memory.memory_link import LINK_TYPES, MemoryLink
from nous.domain.memory.recall_annotator import RecallAnnotation, RecallAnnotator
from nous.domain.memory.recall_governor import RecallGovernor
from nous.domain.memory.repository import (
    MemoryAuxiliaryRepository,
    MemoryRepository,
    MemoryStrengthRepository,
)
from nous.domain.memory.service import MemoryService

# SudachiExtractor / HybridEntityExtractor は __getattr__ で遅延ロード
# （pytest collection 時に sudachipy 辞書のロードを避けるため。辞書は初回使用時に
#  NOUS_DATA_ROOT/sudachi/ へ自動ダウンロードされる）


def __getattr__(name: str):
    if name in ("SudachiExtractor", "HybridEntityExtractor"):
        from nous.domain.memory.sudachi_extractor import (
            HybridEntityExtractor,
            SudachiExtractor,
        )

        return {"SudachiExtractor": SudachiExtractor, "HybridEntityExtractor": HybridEntityExtractor}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "HybridEntityExtractor",
    "LINK_TYPES",
    "Memory",
    "MemoryAuxiliaryRepository",
    "MemoryLink",
    "MemoryRepository",
    "MemoryService",
    "MemoryStrength",
    "MemoryStrengthRepository",
    "RecallAnnotator",
    "RecallAnnotation",
    "RecallGovernor",
    "SimpleEntityExtractor",
    "SudachiExtractor",
]
