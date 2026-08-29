"""tests/unit/test_post_process_expression.py"""

import asyncio

import pytest

from nous.application.event_bus import EVENT_EXPRESSION_CHANGED


def test_event_constant_registered_in_events_router():
    from nous.api.http.routers import events as events_router

    assert EVENT_EXPRESSION_CHANGED == "context.expression_changed"
    assert EVENT_EXPRESSION_CHANGED in events_router._ALL_EVENT_TYPES


@pytest.mark.asyncio
async def test_expression_published_when_image_exists(tmp_path, monkeypatch):
    """画像が既にある場合: イベントバスに即時 publish される。"""
    from nous.application.chat import expression as expr_mod
    from nous.application.chat.pipeline import post as post_mod

    published: list[tuple[str, dict]] = []

    class _Bus:
        async def publish(self, event_type, data):
            published.append((event_type, data))

    class _Ctx:
        persona = "herta"
        event_bus = _Bus()

    monkeypatch.setattr(expr_mod, "resolve_expression_url", lambda p, e: f"/api/chat/{p}/persona/images/expr_{e}.png")
    await post_mod.update_expression(_Ctx(), config=None, emotion="joy")
    assert published == [
        (EVENT_EXPRESSION_CHANGED, {"emotion": "joy", "url": "/api/chat/herta/persona/images/expr_joy.png"})
    ]


@pytest.mark.asyncio
async def test_expression_generation_scheduled_when_missing(tmp_path, monkeypatch):
    """画像が無い場合: 非同期生成タスクがスケジュールされ、即時 publish はされない。"""
    from nous.application.chat import expression as expr_mod
    from nous.application.chat.pipeline import post as post_mod

    published: list[tuple[str, dict]] = []
    scheduled: list[object] = []

    class _Bus:
        async def publish(self, event_type, data):
            published.append((event_type, data))

    class _Ctx:
        persona = "herta"
        event_bus = _Bus()

    monkeypatch.setattr(expr_mod, "resolve_expression_url", lambda p, e: None)

    orig_create_task = asyncio.create_task

    def _spy_create_task(coro, **kwargs):
        scheduled.append(coro)
        return orig_create_task(coro, **kwargs)

    monkeypatch.setattr(post_mod.asyncio, "create_task", _spy_create_task)
    monkeypatch.setattr(post_mod, "_generate_and_publish_expression", lambda *a, **k: _noop())
    await post_mod.update_expression(_Ctx(), config=None, emotion="joy")
    assert published == []
    assert len(scheduled) == 1
    await asyncio.sleep(0)  # 生成タスク（noop）を回収


async def _noop():
    return None


@pytest.mark.asyncio
async def test_expression_task_kept_in_module_registry(tmp_path, monkeypatch):
    """生成タスクはモジュールレベル dict に強参照として保持される。"""
    from nous.application.chat import expression as expr_mod
    from nous.application.chat.pipeline import post as post_mod

    class _Bus:
        async def publish(self, event_type, data):
            pass

    class _Ctx:
        persona = "herta"
        event_bus = _Bus()

    started: list[str] = []

    async def _fake_generate(ctx, config, emotion):
        started.append(emotion)
        await _noop()  # イベントループに一度譲り、タスク生存を確認できるようにする

    post_mod._expression_tasks.clear()
    monkeypatch.setattr(expr_mod, "resolve_expression_url", lambda p, e: None)
    monkeypatch.setattr(post_mod, "_generate_and_publish_expression", _fake_generate)
    await post_mod.update_expression(_Ctx(), config=None, emotion="joy")
    assert ("herta", "joy") in post_mod._expression_tasks
    await asyncio.sleep(0)
    assert started == ["joy"]
    await asyncio.sleep(0)
    # 完了後は dict から除去される
    assert ("herta", "joy") not in post_mod._expression_tasks


@pytest.mark.asyncio
async def test_expression_task_deduped_while_inflight(tmp_path, monkeypatch):
    """同一 (persona, emotion) の生成中は新しいタスクを起こさない。"""
    from nous.application.chat import expression as expr_mod
    from nous.application.chat.pipeline import post as post_mod

    class _Bus:
        async def publish(self, event_type, data):
            pass

    class _Ctx:
        persona = "herta"
        event_bus = _Bus()

    started: list[str] = []
    release = asyncio.Event()

    async def _blocking_generate(ctx, config, emotion):
        started.append(emotion)
        await release.wait()

    post_mod._expression_tasks.clear()
    monkeypatch.setattr(expr_mod, "resolve_expression_url", lambda p, e: None)
    monkeypatch.setattr(post_mod, "_generate_and_publish_expression", _blocking_generate)

    await post_mod.update_expression(_Ctx(), config=None, emotion="joy")
    await asyncio.sleep(0)  # タスクを開始させる
    await post_mod.update_expression(_Ctx(), config=None, emotion="joy")  # in-flight → スキップ
    assert started == ["joy"]
    assert len(post_mod._expression_tasks) == 1

    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert post_mod._expression_tasks == {}
