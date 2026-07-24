from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

T = TypeVar("T")
E = TypeVar("E")


@dataclass(frozen=True, slots=True)
class Success[T]:
    """Successful result wrapper."""

    value: T

    @property
    def is_ok(self) -> bool:
        return True

    def map(self, f: Callable[[T], Any]) -> Success:
        return Success(f(self.value))

    def unwrap(self) -> T:
        return self.value

    def unwrap_or(self, default: T) -> T:
        return self.value

    def and_then(self, f: Callable[[T], Result]) -> Result:
        """Chain another Result-returning operation. Rust `and_then` / Haskell `>>=`."""
        return f(self.value)

    def or_else(self, f: Callable) -> Result:
        """Ignore — Success short-circuits `or_else`."""
        return self


@dataclass(frozen=True, slots=True)
class Failure[E]:
    """Failed result wrapper."""

    error: E

    @property
    def is_ok(self) -> bool:
        return False

    def map(self, f: Callable) -> Failure[E]:
        return self

    def unwrap(self) -> NoReturn:
        raise ValueError(f"Unwrap on Failure: {self.error}")

    def unwrap_or(self, default: Any) -> Any:
        return default

    def and_then(self, f: Callable) -> Failure[E]:
        """Skip — Failure short-circuits `and_then`."""
        return self

    def or_else(self, f: Callable[[E], Result]) -> Result:
        """Recover from error with fallback operation. Rust `or_else`."""
        return f(self.error)


Result = Success[T] | Failure[E]
