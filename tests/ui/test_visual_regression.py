"""Visual regression tests for Nous WebUI.

Uses Playwright's ``to_have_screenshot()`` for pixel-level comparison.
Baseline screenshots are stored in ``tests/ui/screenshots/`` and should be
committed to git.

Prerequisites
-------------
- A running Nous server (default: http://localhost:26262)
- Override the URL with the ``NOUS_TEST_URL`` environment variable
- Playwright browsers installed (``playwright install chromium``)

Usage
-----
    # Generate / update baseline snapshots against a running server
    NOUS_TEST_URL=http://localhost:26262 pytest tests/ui/ --update-snapshots -v

    # Run comparisons against stored baselines
    NOUS_TEST_URL=http://localhost:26262 pytest tests/ui/ -v
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect

# ---------------------------------------------------------------------------
# Viewport presets
# ---------------------------------------------------------------------------
VIEWPORTS = {
    "desktop": {"width": 1920, "height": 1080},
    "tablet": {"width": 768, "height": 1024},
    "mobile": {"width": 390, "height": 844},
}

# Where baseline images live
SCREENSHOTS_DIR = Path(__file__).resolve().parent / "screenshots"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
async def browser_session():
    """Session-scoped Chromium browser instance."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest.fixture
async def desktop_page(browser_session, nous_server):
    """Desktop-viewport page with reduced-motion enabled."""
    context = await browser_session.new_context(
        viewport=VIEWPORTS["desktop"],
        device_scale_factor=1,
        reduced_motion="reduce",
    )
    page = await context.new_page()
    yield page
    await context.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _goto_dashboard(page, nous_server: str) -> None:
    """Navigate to the dashboard root and wait for idle."""
    await page.goto(nous_server + "/", wait_until="networkidle")
    await page.wait_for_timeout(500)


def _snapshot_path(name: str) -> str:
    """Return the absolute path for a baseline screenshot."""
    return str(SCREENSHOTS_DIR / name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.asyncio
async def test_homepage_desktop(desktop_page, nous_server):
    """Dashboard at desktop viewport — full-page snapshot."""
    await _goto_dashboard(desktop_page, nous_server)
    await expect(desktop_page).to_have_screenshot(
        _snapshot_path("homepage-desktop.png"),
        max_diff_pixels=100,
        threshold=0.1,
        animations="disabled",
        full_page=True,
    )


@pytest.mark.ui
@pytest.mark.asyncio
async def test_homepage_mobile(browser_session, nous_server):
    """Dashboard at mobile viewport — full-page snapshot."""
    context = await browser_session.new_context(**VIEWPORTS["mobile"], reduced_motion="reduce")
    page = await context.new_page()
    await _goto_dashboard(page, nous_server)
    await expect(page).to_have_screenshot(
        _snapshot_path("homepage-mobile.png"),
        max_diff_pixels=100,
        threshold=0.1,
        animations="disabled",
        full_page=True,
    )
    await context.close()


@pytest.mark.ui
@pytest.mark.asyncio
async def test_chat_tab(desktop_page, nous_server):
    """Chat tab at desktop viewport."""
    await _goto_dashboard(desktop_page, nous_server)
    # Click the Chat tab if present
    chat_tab = desktop_page.locator('button[data-tab="chat"]')
    if await chat_tab.count() > 0:
        await chat_tab.click()
        await desktop_page.wait_for_timeout(500)
    await expect(desktop_page).to_have_screenshot(
        _snapshot_path("chat-tab-desktop.png"),
        max_diff_pixels=100,
        threshold=0.1,
        animations="disabled",
    )


@pytest.mark.ui
@pytest.mark.asyncio
async def test_settings_tab(desktop_page, nous_server):
    """Settings tab at desktop viewport."""
    await _goto_dashboard(desktop_page, nous_server)
    settings_tab = desktop_page.locator('button[data-tab="settings"]')
    if await settings_tab.count() > 0:
        await settings_tab.click()
        await desktop_page.wait_for_timeout(500)
    await expect(desktop_page).to_have_screenshot(
        _snapshot_path("settings-tab-desktop.png"),
        max_diff_pixels=100,
        threshold=0.1,
        animations="disabled",
    )
