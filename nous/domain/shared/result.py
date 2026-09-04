from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")
E = TypeVar("E")


@dataclass(frozen=True, slots=True)
class Success[T]:
    """Successful result wrapper."""

    value: T

    @property
    def is_ok(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class Failure[E]:
    """Failed result wrapper."""

    error: E

    @property
    def is_ok(self) -> bool:
        return False


Result = Success[T] | Failure[E]
