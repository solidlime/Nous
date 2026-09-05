"""Task 5: PostProcessStep background tasks are bounded and self-cleaning."""

from __future__ import annotations

import asyncio

from nous.application.chat.pipeline import post as post_mod


async def test_done_tasks_leave_set():
    t = asyncio.create_task(asyncio.sleep(0))
    post_mod._track_background(t)
    assert t in post_mod._background_tasks
    await t
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert t not in post_mod._background_tasks


async def test_cap_drops_new_task():
    evt = asyncio.Event()

    async def _block() -> None:
        await evt.wait()

    holders = [asyncio.create_task(_block()) for _ in range(post_mod._MAX_BACKGROUND_TASKS)]
    try:
        for h in holders:
            post_mod._track_background(h)
        assert len(post_mod._background_tasks) == post_mod._MAX_BACKGROUND_TASKS
        extra = asyncio.create_task(asyncio.sleep(0))
        post_mod._track_background(extra)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert extra.cancelled()
        assert len(post_mod._background_tasks) <= post_mod._MAX_BACKGROUND_TASKS
    finally:
        evt.set()
        await asyncio.gather(*holders, return_exceptions=True)
