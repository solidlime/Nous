"""Tests for _infer_kind() in auto_capture.py + PostProcessStep auto_capture throttle."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from nous.application.chat.pipeline import post as post_module
from nous.application.chat.pipeline.auto_capture import _infer_kind
from nous.application.chat.pipeline.post import PostProcessStep


class TestInferKind:
    """Infer memory kind from content patterns."""

    # ── Episodic ──────────────────────────────────────────────────────

    @pytest.mark.parametrize("content", [
        "昨日カフェに行った",
        "先週末に京都を訪れた",
        "前回のミーティングでその話をした",
        "この前の打ち合わせで決まった",
        "あの時は本当に困った",
    ])
    def test_infer_episodic_from_time(self, content: str) -> None:
        assert _infer_kind(content, "fact") == "episodic"

    @pytest.mark.parametrize("content", [
        "渋谷で友達に会った",
        "駅前の喫茶店で勉強していた",
    ])
    def test_infer_episodic_from_place(self, content: str) -> None:
        assert _infer_kind(content, "fact") == "episodic"

    @pytest.mark.parametrize("content", [
        "来週までにこの機能を完成させることにした",
        "明日の朝9時に打ち合わせを入れた",
    ])
    def test_infer_episodic_decision(self, content: str) -> None:
        assert _infer_kind(content, "decision") == "episodic"

    # ── Procedural ────────────────────────────────────────────────────

    @pytest.mark.parametrize("content", [
        "このエラーは再起動すれば直る",
        "ファイルを保存するにはCtrl+Sを押せばいい",
        "Pythonの仮想環境の作り方",
        "依存関係をインストールする方法",
    ])
    def test_infer_procedural(self, content: str) -> None:
        assert _infer_kind(content, "fact") == "procedural"

    @pytest.mark.parametrize("content", [
        "バグを直すにはまず再現手順を確認するとうまくいく",
        "このAPIを叩くときは認証ヘッダーをつければいい",
    ])
    def test_infer_procedural_howto(self, content: str) -> None:
        assert _infer_kind(content, "fact") == "procedural"

    # ── Semantic ──────────────────────────────────────────────────────

    @pytest.mark.parametrize("content", [
        "Pythonは動的型付け言語",
        "地球は太陽の周りを回っている",
    ])
    def test_infer_semantic_default(self, content: str) -> None:
        assert _infer_kind(content, "fact") == "semantic"

    @pytest.mark.parametrize("content", [
        "コーヒーより紅茶が好き",
        "私は抹茶味の方がいい",
    ])
    def test_infer_semantic_preference(self, content: str) -> None:
        assert _infer_kind(content, "preference") == "semantic"

    @pytest.mark.parametrize("content", [
        "Reactは学習コストが高いという問題がある",
        "",
        "   ",
        "a",
    ])
    def test_infer_semantic_edge(self, content: str) -> None:
        """Edge/short/empty content should default to semantic."""
        assert _infer_kind(content, "problem") == "semantic"


# ── PostProcessStep auto_capture throttle ────────────────────────────


def _make_throttle_fixtures(interval: int):
    ctx = SimpleNamespace(
        persona="p1",
        persona_service=SimpleNamespace(record_conversation_time=lambda p: None),
    )
    config = SimpleNamespace(
        session_summarize=False,
        auto_capture_enabled=True,
        auto_capture_interval=interval,
        auto_capture_max_memories=5,
        reflection_enabled=False,
        mental_model_enabled=False,
        auto_extract=False,
        provider="anthropic",
        get_effective_model=lambda: "m",
    )
    session = SimpleNamespace(_messages=[{"role": "user", "content": "hi"}], evict_callback=None)
    turn_ctx = SimpleNamespace(
        full_response="ok",
        was_truncated=False,
        usage={},
        user_msg_id="u",
        assistant_msg_id="a",
        memories_raw=[],
        user_message="hi",
        tool_calls_log=[],
        system_prompt="",
        state_raw="",
        context_section="",
        memory_debug={},
        skills_raw=[],
        messages=[],
    )
    return ctx, config, session, turn_ctx


def _run_step(ctx, config, session, turn_ctx) -> None:
    async def _consume():
        step = PostProcessStep()
        async for _ in step.run(ctx=ctx, config=config, session=session, turn_ctx=turn_ctx):
            pass

    asyncio.run(_consume())


class TestAutoCaptureThrottle:
    def test_second_call_within_interval_suppressed_across_instances(self, monkeypatch):
        """別インスタンスでも interval 未満の2連続呼び出しは2回目が抑制される."""
        calls: list = []

        async def fake_run_auto_capture(**kwargs):
            calls.append(kwargs)

        monkeypatch.setattr(post_module, "_last_auto_capture_at", {})
        monkeypatch.setattr("nous.application.chat.pipeline.auto_capture.run_auto_capture", fake_run_auto_capture)
        ctx, config, session, turn_ctx = _make_throttle_fixtures(interval=300)

        _run_step(ctx, config, session, turn_ctx)
        _run_step(ctx, config, session, turn_ctx)

        assert len(calls) == 1

    def test_interval_zero_runs_every_time(self, monkeypatch):
        """interval=0 は毎回実行."""
        calls: list = []

        async def fake_run_auto_capture(**kwargs):
            calls.append(kwargs)

        monkeypatch.setattr(post_module, "_last_auto_capture_at", {})
        monkeypatch.setattr("nous.application.chat.pipeline.auto_capture.run_auto_capture", fake_run_auto_capture)
        ctx, config, session, turn_ctx = _make_throttle_fixtures(interval=0)

        _run_step(ctx, config, session, turn_ctx)
        _run_step(ctx, config, session, turn_ctx)

        assert len(calls) == 2
