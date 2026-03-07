"""
日次日記タスク（夜に自動実行）。

直近24時間の記憶を LLM で日記文体に要約して memory_db に tags=["diary"] で保存する。
スケジューラーや trigger_task("daily_diary") から呼ばれる。
"""

import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# LLM に渡す要約プロンプトのテンプレート
_DIARY_PROMPT_TEMPLATE = """\
以下は今日の記憶の断片です。これらをまとめて、{persona} の視点から日記風に書いてください。
一人称で、感情や思考を交えた300文字程度の日記文にしてください。

[今日の記憶]
{memories_text}

日記:"""


async def run_daily_diary(
    agent_loop: object,
    llm_router: Any,
    memory_db: Any,
    persona: str,
) -> str:
    """直近24時間の記憶を要約して日記として保存する。

    1. memory_db.get_recent(limit=20) で直近記憶を取得。
    2. LLM（task_type="summarization"）で日記文体に要約。
    3. memory_db に tags=["diary"] で保存する。

    Args:
        agent_loop: AgentLoop インスタンス（現在は未使用・将来の拡張用）。
        llm_router: LLMRouter インスタンス（要約生成に使用）。
        memory_db: MemoryDB インスタンス（記憶取得・保存に使用）。
        persona: ペルソナ名（プロンプトに埋め込む）。

    Returns:
        実行結果を表す文字列。保存した場合はキーを含む。
    """
    try:
        # 直近24時間以内の記憶を取得する
        # MemoryDB には created_at フィルタがないため get_recent で取得してから絞り込む
        cutoff = datetime.now() - timedelta(hours=24)
        recent = memory_db.get_recent(limit=20)
        today_memories = [
            m for m in recent
            if m.created_at >= cutoff.isoformat()
        ]

        if not today_memories:
            logger.info(f"[{persona}] 日記生成: 直近24時間の記憶なし（スキップ）")
            return "daily_diary skipped: no recent memories"

        # 記憶を箇条書きに変換
        memories_text = "\n".join(
            f"- {m.content[:100]}{'...' if len(m.content) > 100 else ''}"
            for m in today_memories
        )

        prompt = _DIARY_PROMPT_TEMPLATE.format(
            persona=persona,
            memories_text=memories_text,
        )

        from llm.base import Message
        response = await llm_router.generate(
            messages=[Message(role="user", content=prompt)],
            task_type="summarization",
        )

        diary_content = response.content.strip()
        if not diary_content or diary_content == "[LLM unavailable]":
            logger.warning(f"[{persona}] 日記生成失敗: LLM からコンテンツなし")
            return "daily_diary failed: LLM unavailable"

        # memory_db に日記として保存
        from memory.schema import MemoryEntry
        now = datetime.now().isoformat()
        key = memory_db.generate_key()
        date_str = datetime.now().strftime("%Y-%m-%d")
        entry = MemoryEntry(
            key=key,
            content=f"[日記 {date_str}]\n{diary_content}",
            created_at=now,
            updated_at=now,
            tags=["diary"],
            importance=0.6,
        )
        success = memory_db.save(entry)
        if success:
            logger.info(f"[{persona}] 日記保存成功: key={key}")
            return f"daily_diary saved: {key}"
        return "daily_diary save failed"

    except Exception as e:
        logger.error(f"[{persona}] 日次日記タスクエラー: {e}", exc_info=True)
        return f"daily_diary error: {e}"
