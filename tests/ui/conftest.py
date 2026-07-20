"""Playwright UI test configuration.

Usage
-----
Run with a running server:
    NOUS_TEST_URL=http://localhost:26262 pytest tests/ui/ -v

Update baseline screenshots:
    pytest tests/ui/ --update-snapshots -v
"""

import os

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Update visual regression baseline screenshots",
    )


@pytest.fixture(scope="session")
def nous_server(request) -> str:
    """Return the base URL of the Nous server under test.

    Checks the ``NOUS_TEST_URL`` environment variable first. If unset,
    defaults to ``http://localhost:26262`` (the default port).
    """
    url = os.environ.get("NOUS_TEST_URL")
    if url is not None:
        return url.rstrip("/")

    # Use the project's default port (see nous/config/settings.py:45)
    return "http://localhost:26262"


@pytest.fixture(scope="session")
def update_snapshots(request) -> bool:
    """Whether the ``--update-snapshots`` CLI flag was passed."""
    return request.config.getoption("--update-snapshots")
