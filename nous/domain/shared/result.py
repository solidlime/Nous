from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeVar

T = TypeVar("T")
E = TypeVar("E")


@dataclass(frozen=True, slots=True)
class Success[T]:
    """Successful result wrapper.

    ``is_ok`` は Literal 判別子フィールド: mypy が ``if result.is_ok:`` の
    分岐で Success/Failure を狭窄する（property では型ガードが効かないため）。
    """

    value: T
    is_ok: Literal[True] = True


@dataclass(frozen=True, slots=True)
class Failure[E]:
    """Failed result wrapper."""

    error: E
    is_ok: Literal[False] = False


Result = Success[T] | Failure[E]
