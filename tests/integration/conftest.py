"""Integration-test fixtures.

The app under test creates AppContext, which starts background model
preload threads (snapshot_download + ONNX session creation).  Those threads
are daemons and outlive fast-running pytest processes: they can still be
inside ``huggingface_hub.snapshot_download`` (which uses a
``ThreadPoolExecutor``) when the interpreter shuts down, raising::

    RuntimeError: cannot schedule new futures after interpreter shutdown

Integration tests do not need real models (Qdrant is intentionally
unreachable; keyword fallback is what is being verified), so preload is
disabled here.  The cold-start fallback paths (``is_loaded`` guards) are
exercised by unit tests with mocked models.
"""

from __future__ import annotations

import pytest

from nous.application import use_cases
from nous.application.use_cases import AppContextRegistry


@pytest.fixture(autouse=True)
def _disable_model_preload(monkeypatch):
    """No-op the background model preload so no daemon threads leak out of tests."""

    def _noop(self) -> None:  # noqa: ANN001
        pass

    monkeypatch.setattr(use_cases.AppContext, "_preload_background", _noop)


@pytest.fixture()
def _auto_persona_dirs(_reset_singletons):
    """AppContextRegistry now requires an existing persona directory (memory-DoS fix).

    Integration tests rarely pre-create personas, so auto-create the
    directory on get() to restore the legacy behaviour for tests.
    Security tests that verify the strict behaviour must NOT use this fixture.
    """
    from pathlib import Path

    original_get = AppContextRegistry.get.__func__

    def _get_with_mkdir(cls, persona, config=None):
        settings = AppContextRegistry._settings
        if settings is not None:
            Path(settings.persona_dir).joinpath(persona).mkdir(parents=True, exist_ok=True)
        return original_get(cls, persona, config)

    AppContextRegistry.get = classmethod(_get_with_mkdir)  # type: ignore[attr-defined]
    yield
    AppContextRegistry.get = classmethod(original_get)  # type: ignore[attr-defined]
