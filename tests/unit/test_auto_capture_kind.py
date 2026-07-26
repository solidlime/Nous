"""Tests for _infer_kind() in auto_capture.py."""

import pytest

from nous.application.chat.pipeline.auto_capture import _infer_kind


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
