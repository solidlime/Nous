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


@pytest.fixture(autouse=True)
def _disable_model_preload(monkeypatch):
    """No-op the background model preload so no daemon threads leak out of tests."""

    def _noop(self) -> None:  # noqa: ANN001
        pass

    monkeypatch.setattr(use_cases.AppContext, "_preload_background", _noop)
