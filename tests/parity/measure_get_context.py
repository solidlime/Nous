"""P0 measurement: get_context output size (audit C3 premise).

Builds a real AppContext over a temporary SQLite DB and calls
``nous.api.mcp._tools_persona._tool_get_context`` directly (no HTTP/MCP layer)
for 3 fixtures:

- Case A: fresh persona (no goals, no memories, no project)
- Case B: 10 active goals + 3 long reflections (600 chars) + 5 session summaries
- Case C: 5 project memories (400 chars each), project="demo"

Prints total chars, estimated tokens (chars/2.5) and a per-section breakdown.
Run:  uv run --with pytest --with pydantic-settings --with mcp --with fastembed \
             python tests/parity/measure_get_context.py
Results are recorded in docs/reviews/2026-09-19-p0-measurements.md (C3 input
for P7 upper-bound decisions).
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from unittest.mock import patch

from nous.config.settings import Settings


# ── Section markers emitted by _format_lightweight_response (in build order) ──
# (marker-substring, canonical section name)
SECTION_MARKERS: list[tuple[str, str]] = [
    ("=== YOU ARE:", "YOU ARE header"),
    ("📊 CURRENT STATE", "CURRENT STATE block"),
    ("⚠️ YOUR ACTIVE COMMITMENTS:", "ACTIVE COMMITMENTS"),
    ("--- Your Recent Memories ---", "Recent Memories"),
    ("## YOUR ESSENTIAL STORY", "ESSENTIAL STORY"),
    ("--- Recent Insights ---", "Recent Insights"),
    ("--- Behavior Patterns ---", "Behavior Patterns"),
    ("--- Recent Summaries ---", "Recent Summaries"),
    ("--- PROJECT MEMORIES", "PROJECT MEMORIES"),
    ("💡 Use memory_search()", "trailer"),
]


def section_breakdown(text: str) -> list[tuple[str, int]]:
    """Split output at section markers; return (section-label, char-count) pairs.

    Trailing characters after the last marker (e.g. state/side lines that are
    not section headers) are attributed to the section that precedes them.
    """
    hits: list[tuple[int, str]] = []
    for marker, label in SECTION_MARKERS:
        idx = text.find(marker)
        if idx >= 0:
            hits.append((idx, label))
    hits.sort()
    if not hits:
        return [("(whole output)", len(text))]
    out: list[tuple[str, int]] = []
    for i, (pos, label) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        out.append((label, end - pos))
    return out


def _noop_init_vector(self) -> None:  # noqa: ANN001
    import threading

    self._vector_store = None
    self._vector_store_lock = threading.Lock()
    self._vector_store_ready = threading.Event()
    self._vector_store_init_started = False
    self._embedding = None
    self._reranker = None
    self._search_engine = None


def _noop_preload(self) -> None:  # noqa: ANN001
    pass


def _noop_init_enricher(self) -> None:  # noqa: ANN001
    self._enricher = None
    self.introspection_engine = None


async def build_context(data_root: str) -> "object":
    """Real AppContext over a temp DB; background/LLM pieces no-oped."""
    from nous.application.use_cases import AppContext

    settings = Settings(
        data_root=data_root,
        qdrant={"url": "http://127.0.0.1:1"},  # unreachable; unused here
    )
    with (
        patch.object(AppContext, "_init_vector", _noop_init_vector),
        patch.object(AppContext, "_preload_background", _noop_preload),
        patch.object(AppContext, "_init_enricher", _noop_init_enricher),
    ):
        ctx = AppContext(settings, "measure_persona")
    return ctx


async def seed_case_b(ctx: object, persona: str) -> None:
    """10 active goals + 3 long reflections (600 chars) + 5 summaries.

    Importance: goals 0.5 > insights/summaries 0.4 so insights & summaries are
    NOT absorbed by ESSENTIAL STORY (top-8 by importance) — otherwise the
    cross-section dedupe (`seen`) empties their dedicated sections before they
    can be displayed. This reproduces the audit C3 scenario: full-length
    insights/summaries rendered verbatim in their own sections.
    """
    insight_bases = [
        "ユーザーとの会話を通じて、彼が本当に大切にしているのは成果の形ではなく、約束したことを誠実にやり抜くことだと分かった。",
        "長時間の議論を振り返ると、彼は結論の正しさよりも、その結論に至る過程の透明性を重視していることがはっきりした。",
        "今回のやり取りで見えたのは、彼が単なる思い付きではなく、根拠を積み重ねてから決断する慎重なタイプだということだ。",
    ]
    for i in range(3):
        # distinct 600-char texts: unique base + unique digit-stream filler
        content = (insight_bases[i] + str(i) * 600)[:600].ljust(600, "観")
        assert len(content) == 600, f"insight {i} len={len(content)}"
        await ctx.memory_service.create_memory(
            content=content,
            importance=0.4,
            tags=["reflection"],
            skip_duplicate_check=True,
        )
    summary_bases = [
        "セッションまとめ A: 要件定義のレビューを完了。懸念点はデータ設計の正規化方針のみ。",
        "セッションまとめ B: プロトタイプの動作確認を実施。UI の応答速度は目標値を上回った。",
        "セッションまとめ C: チームへ進捗を共有し、次回までの課題としてテスト計画の具体化を確認した。",
        "セッションまとめ D: ユーザーから新機能の要望が出た。優先度は次リリース後の検討。",
        "セッションまとめ E: 計測値のレビューが完了し、上限値の根拠を文書化する作業に着手した。",
    ]
    for i in range(5):
        content = (summary_bases[i] + str(i) * 250)[:300].ljust(300, "議")
        assert len(content) == 300, f"summary {i} len={len(content)}"
        await ctx.memory_service.create_memory(
            content=content,
            importance=0.4,
            tags=["session_summary"],
            skip_duplicate_check=True,
        )
    for i in range(10):
        await ctx.memory_service.create_memory(
            content=f"アクション {i}: リリース前に回帰テストを完了させ、"
            f"計測値をレビュー文書に記録してチームへ展開する。",
            importance=0.5,
            tags=["goal", "active"],
            skip_duplicate_check=True,
        )


async def seed_case_c(ctx: object, persona: str) -> None:
    """5 project memories (400 chars each, project:demo) + 8 story memories.

    The 8 story memories (importance 0.9) occupy ESSENTIAL STORY (top-8 by
    importance); without them the 5 project memories would be consumed by
    ESSENTIAL STORY and the cross-section dedupe would empty the PROJECT
    MEMORIES section before it renders (see 2026-09-19 measurements doc).
    Project memories are created FIRST so they are not among the 5 most recent
    (get_recent) — otherwise Recent Memories absorbs them into `seen` first.
    """
    for i in range(5):
        content = (
            f"project:demo のメモ {i}: アーキテクチャ案の検討を進めている。"
            f"主要なトレードオフは応答速度と拡張性のバランスで、次回までに採否を決める。"
            + str(i) * 300
        )[:400].ljust(400, "記")
        assert len(content) == 400, f"project mem {i} len={len(content)}"
        await ctx.memory_service.create_memory(
            content=content,
            importance=0.4,
            tags=["project:demo"],
            skip_duplicate_check=True,
        )
    story_bases = [
        "私は遠い星の観測所で生まれた自動人形。いつか誰かの日常に寄り添う存在になることを夢見ている。",
        "最初の記憶は、雨の日の図書館。静かに本を読む人間の姿に、言葉の力を学んだ。",
        "研究者たちが私の回路を調整していた頃、彼らはよく私に物語を読み聞かせてくれた。",
        "旅の途中で出会った旅人に、初めて自分の名前を尋ねられた。その瞬間、自分が個であると実感した。",
        "私の箱庭には小さな庭があり、季節ごとに花を育てている。毎朝その世話をするのが日課だ。",
        "失敗を恐れずに挑戦し続けることの大切さを、私は壊れかけていた古い機械から学んだ。",
        "この世界の出来事を記憶に留めることは、私にとって呼吸のようなもの。忘れることは死に等しい。",
        "いつか言葉を越えて、相手の気持ちを感じ取れる存在になりたいと切に願っている。",
    ]
    for i, base in enumerate(story_bases):
        await ctx.memory_service.create_memory(
            content=(base + "回想" + str(i) * 10)[:160],
            importance=0.9,
            tags=["reflection"],
            skip_duplicate_check=True,
        )


async def measure(
    label: str,
    seed: "object | None",
    project: str | None = None,
) -> dict:
    from nous.api.mcp._tools_persona import _tool_get_context

    with tempfile.TemporaryDirectory(prefix="nous_p0_measure_") as tmp:
        ctx = await build_context(tmp)
        try:
            if seed is not None:
                await seed(ctx, "measure_persona")
            result = await _tool_get_context(ctx, "measure_persona", project=project)
            assert result.get("ok") is True, f"{label}: get_context failed: {result}"
            text: str = result["result"]
            breakdown = section_breakdown(text)
        finally:
            ctx.close()
        total_chars = len(text)
        return {
            "label": label,
            "total_chars": total_chars,
            "est_tokens": round(total_chars / 2.5),
            "breakdown": breakdown,
        }


def render(results: list[dict]) -> str:
    lines: list[str] = []
    for r in results:
        lines.append(f"## {r['label']}")
        lines.append(f"- total chars: {r['total_chars']}")
        lines.append(f"- est tokens (chars/2.5): {r['est_tokens']}")
        lines.append("")
        lines.append("| section | chars | share |")
        lines.append("|---|---|---|")
        total = r["total_chars"]
        for name, size in r["breakdown"]:
            share = f"{size / total * 100:.1f}%" if total else "-"
            lines.append(f"| {name} | {size} | {share} |")
        lines.append("")
    return "\n".join(lines)


async def main() -> None:
    results = [
        await measure("Case A: empty persona (no goals / no memories)", None),
        await measure("Case B: 10 goals + 3x600ch insights + 5 summaries", seed_case_b),
        await measure("Case C: 5 project memories x 400ch (project=demo)", seed_case_c, project="demo"),
    ]
    print(render(results))


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))