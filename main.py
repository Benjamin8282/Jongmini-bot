import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from core.dnf_api import preload_item_cache
from core.logger import logger
import discord
from discord.ext import commands
from dotenv import load_dotenv
from core.db import init_db

# tasks import
from tasks.daily_aggregation import daily_aggregation_task
from tasks.monthly_aggregation import aggregate_monthly_items_and_notify
from tasks.notify_items import periodic_notify
from tasks.weekly_aggregation import aggregate_weekly_items_and_notify
from tasks.weekly_character_aggregation import aggregate_weekly_items_by_character  # 캐릭터별 주간 집계 task

# commands import
from commands.hello import hello_command
from commands.register import register_command
from commands.total import total_command
from commands.set_output_channel import set_output_channel
from commands.today_status import today_status
from commands.weekly_status import weekly_status
from commands.monthly_status import monthly_status
from commands.weekly_character_status import weekly_character_status  # 캐릭터별 주간 집계 커맨드
from commands.season_status import season_status

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")


def get_scheduler_timezone():
    local_tz = datetime.now().astimezone().tzinfo
    logger.info(f"시스템 로컬 타임존: {local_tz}")
    if str(local_tz) == "Asia/Seoul":
        logger.info("로컬 타임존이 Asia/Seoul 이므로 scheduler timezone 지정 안 함")
        return None  # 시스템 로컬 시간대 사용
    else:
        seoul_tz = ZoneInfo("Asia/Seoul")
        logger.info("로컬 타임존이 Asia/Seoul 아님, scheduler timezone을 Asia/Seoul로 지정함")
        return seoul_tz


class JongminiBot(commands.Bot):
    def __init__(self):
        scheduler_tz = get_scheduler_timezone()
        self.scheduler = AsyncIOScheduler(timezone=scheduler_tz)
        super().__init__(command_prefix="!", intents=discord.Intents.default())
        logger.info("JongminiBot 인스턴스 생성됨")

    async def setup_hook(self):
        logger.info("봇 setup_hook 시작 - DB 초기화 및 명령어 등록")
        await init_db()
        logger.info("DB 초기화 완료")
        await preload_item_cache()

        self.tree.add_command(hello_command)
        self.tree.add_command(register_command)
        self.tree.add_command(total_command)
        self.tree.add_command(set_output_channel)
        self.tree.add_command(today_status)
        self.tree.add_command(weekly_status)
        self.tree.add_command(monthly_status)
        self.tree.add_command(weekly_character_status)
        self.tree.add_command(season_status)

        await self.tree.sync()
        logger.info(f"슬래시 명령어 동기화 완료: {self.tree.get_commands()}")


bot = JongminiBot()


@bot.event
async def on_ready():
    logger.info(f"종미니 봇 로그인 성공: {bot.user}")
    print(f"✅ 종미니 봇 로그인 성공: {bot.user}")

    guild_id = "374494724725145600"  # 실제 서버 ID로 교체하세요

    # 기존 알림 task
    if not hasattr(bot, 'notify_task') or bot.notify_task.done():
        bot.notify_task = asyncio.create_task(periodic_notify(bot, guild_id))
        logger.info("타임라인 아이템 알림 task 시작됨")

    # 신규 일간 집계 task
    if not hasattr(bot, 'daily_aggregation_task') or bot.daily_aggregation_task.done():
        bot.daily_aggregation_task = asyncio.create_task(daily_aggregation_task(bot, guild_id))
        logger.info("일간 모험단 집계 task 시작됨")

    # APScheduler 스케줄러 시작 및 작업 등록
    if not bot.scheduler.running:
        bot.scheduler.start()
        logger.info("스케줄러 시작됨")

    # 스케줄러 타임존 변수
    scheduler_tz = bot.scheduler.timezone

    # 주간 집계: 매주 목요일 06:00 실행
    bot.scheduler.add_job(
        aggregate_weekly_items_and_notify,
        trigger=CronTrigger(day_of_week="thu", hour=5, minute=59, timezone=scheduler_tz),
        args=[bot, guild_id],
        id="weekly_aggregation_job",
        replace_existing=True
    )
    logger.info("주간 집계 작업 스케줄 등록됨 (매주 목요일 05:59)")

    # 월간 집계: 매월 1일 06:00 실행
    bot.scheduler.add_job(
        aggregate_monthly_items_and_notify,
        trigger=CronTrigger(day=1, hour=5, minute=59, timezone=scheduler_tz),
        args=[bot, guild_id],
        id="monthly_aggregation_job",
        replace_existing=True
    )
    logger.info("월간 집계 작업 스케줄 등록됨 (매월 1일 05:59)")

    # 캐릭터별 주간 집계: 매주 목요일 06:01 실행
    bot.scheduler.add_job(
        aggregate_weekly_items_by_character,
        trigger=CronTrigger(day_of_week="thu", hour=5, minute=59, timezone=scheduler_tz),
        args=[bot, guild_id],
        id="weekly_character_aggregation_job",
        replace_existing=True
    )
    logger.info("캐릭터별 주간 집계 작업 스케줄 등록됨 (매주 목요일 05:59)")


bot.run(TOKEN)
