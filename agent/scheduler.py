"""
APScheduler ベースのエージェントスケジューラー。

意識ティック強制発火・記憶減衰チェック・昇華バッチ・ドライブティックを
cron ジョブとして管理する。
"""

import logging
from typing import List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from agent.event_bus import AgentEvent, EventBus, EventType

logger = logging.getLogger(__name__)


class AgentScheduler:
    """APScheduler を使ってエージェントの定時処理をスケジューリングする。

    設定キー（config["consciousness"]["force_ticks"]）に cron 文字列のリストを指定すると
    その時刻に CONSCIOUSNESS_TICK イベントが発火される。

    Args:
        event_bus: イベントを投入する EventBus インスタンス。
        config: Nous 設定 dict（load_config() の返り値）。
    """

    def __init__(self, event_bus: EventBus, config: dict) -> None:
        self._scheduler = AsyncIOScheduler()
        self._event_bus = event_bus
        self._config = config

    def start(self) -> None:
        """スケジューラーを起動して設定に従い cron ジョブを登録する。

        登録するジョブ:
        - consciousness.force_ticks: 意識ティック強制発火
        - schedules.memory_decay: 記憶減衰チェック（SCHEDULE_TRIGGER）
        - schedules.elevation_batch: 昇華バッチ（SCHEDULE_TRIGGER）
        - schedules.drive_tick: ドライブティック（SCHEDULE_TRIGGER）
        """
        consciousness_cfg = self._config.get("consciousness", {})
        schedules_cfg = self._config.get("schedules", {})
        persona = self._config.get("default_persona", "unknown")

        # 意識ティック強制発火（例: ["0 7 * * *", "0 23 * * *"]）
        force_ticks: List[str] = consciousness_cfg.get("force_ticks", [])
        for cron_expr in force_ticks:
            try:
                trigger = self._parse_cron(cron_expr)
                self._scheduler.add_job(
                    self._fire_consciousness_tick,
                    trigger=trigger,
                    args=[persona],
                    id=f"consciousness_tick_{cron_expr}",
                    replace_existing=True,
                )
                logger.info(f"意識ティック cron 登録: {cron_expr}")
            except Exception as e:
                logger.warning(f"意識ティック cron 登録失敗 ({cron_expr}): {e}")

        # 記憶減衰チェック
        memory_decay_cron = schedules_cfg.get("memory_decay")
        if memory_decay_cron:
            try:
                trigger = self._parse_cron(memory_decay_cron)
                self._scheduler.add_job(
                    self._fire_schedule_trigger,
                    trigger=trigger,
                    args=[persona, "memory_decay"],
                    id="memory_decay",
                    replace_existing=True,
                )
                logger.info(f"記憶減衰チェック cron 登録: {memory_decay_cron}")
            except Exception as e:
                logger.warning(f"記憶減衰 cron 登録失敗: {e}")

        # 昇華バッチ
        elevation_cron = schedules_cfg.get("elevation_batch")
        if elevation_cron:
            try:
                trigger = self._parse_cron(elevation_cron)
                self._scheduler.add_job(
                    self._fire_schedule_trigger,
                    trigger=trigger,
                    args=[persona, "elevation_batch"],
                    id="elevation_batch",
                    replace_existing=True,
                )
                logger.info(f"昇華バッチ cron 登録: {elevation_cron}")
            except Exception as e:
                logger.warning(f"昇華バッチ cron 登録失敗: {e}")

        # ドライブティック
        drive_tick_cron = schedules_cfg.get("drive_tick")
        if drive_tick_cron:
            try:
                trigger = self._parse_cron(drive_tick_cron)
                self._scheduler.add_job(
                    self._fire_schedule_trigger,
                    trigger=trigger,
                    args=[persona, "drive_tick"],
                    id="drive_tick",
                    replace_existing=True,
                )
                logger.info(f"ドライブティック cron 登録: {drive_tick_cron}")
            except Exception as e:
                logger.warning(f"ドライブティック cron 登録失敗: {e}")

        self._scheduler.start()
        logger.info("AgentScheduler 起動完了")

    def stop(self) -> None:
        """スケジューラーをシャットダウンする。実行中ジョブは待たずに停止する。"""
        try:
            self._scheduler.shutdown(wait=False)
        except Exception as e:
            logger.warning(f"AgentScheduler 停止中にエラー: {e}")

    async def _fire_consciousness_tick(self, persona: str) -> None:
        """意識ティックイベントをキューに投入する。"""
        event = AgentEvent(
            priority=3,
            event_type=EventType.CONSCIOUSNESS_TICK,
            persona=persona,
            data={"source": "scheduler"},
        )
        await self._event_bus.put(event)
        logger.debug(f"意識ティックイベント投入 (scheduler): {persona}")

    async def _fire_schedule_trigger(self, persona: str, task_name: str) -> None:
        """スケジュール定時タスクをキューに投入する。"""
        event = AgentEvent(
            priority=5,
            event_type=EventType.SCHEDULE_TRIGGER,
            persona=persona,
            data={"task": task_name},
        )
        await self._event_bus.put(event)
        logger.debug(f"スケジュールイベント投入: {task_name} ({persona})")

    @staticmethod
    def _parse_cron(cron_expr: str) -> CronTrigger:
        """cron 文字列 "分 時 日 月 曜" を CronTrigger に変換する。

        Args:
            cron_expr: スペース区切り5フィールドの cron 式（例: "0 7 * * *"）。

        Returns:
            APScheduler の CronTrigger インスタンス。

        Raises:
            ValueError: フィールド数が5でない場合。
        """
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"cron 式は5フィールド必要: '{cron_expr}'")
        minute, hour, day, month, day_of_week = parts
        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
        )
