import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from core.dnf_api import preload_item_cache
from core.logger import logger
import discord
from core.chat_moderator import ChatModerator
from discord.ext import commands
from dotenv import load_dotenv
from core.db import init_db

# tasks import
from tasks.daily_aggregation import daily_aggregation_task
from tasks.monthly_aggregation import monthly_aggregation_task
from tasks.notify_items import periodic_notify
from tasks.weekly_aggregation import weekly_aggregation_task
# from tasks.weekly_character_aggregation import aggregate_weekly_items_by_character  # 캐릭터별 주간 집계 task (미사용)
from tasks.poll_auction_prices import poll_auction_prices

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
from commands.dundam_ranking import dundam_ranking
from commands.dundam_exclusion import dundam_exclusion
from commands.adventure_dundam_ranking import adventure_dundam_ranking
from commands.auction_watch import (
    auction_watch_register, auction_watch_unregister, auction_watch_list
)
from commands.auction_chart import auction_chart
from commands.auction_overview import auction_overview

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")  # 디폴트 값 설정


def get_scheduler_timezone():
    # UTC 고정
    utc_tz = ZoneInfo("Asia/Seoul")  # KST로 설정
    logger.info(f"스케줄러 타임존으로 KST 고정: {utc_tz}")
    return utc_tz


class JongminiBot(commands.Bot):
    def __init__(self):
        scheduler_tz = get_scheduler_timezone()
        self.scheduler = AsyncIOScheduler(timezone=scheduler_tz)

        intents = discord.Intents.default()
        intents.messages = True
        intents.message_content = True

        super().__init__(command_prefix="!", intents=intents)
        self.chat_moderator = ChatModerator()
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
        self.tree.add_command(dundam_ranking)
        self.tree.add_command(dundam_exclusion)
        self.tree.add_command(adventure_dundam_ranking)
        self.tree.add_command(auction_watch_register)
        self.tree.add_command(auction_watch_unregister)
        self.tree.add_command(auction_watch_list)
        self.tree.add_command(auction_chart)
        self.tree.add_command(auction_overview)
        logger.info("커맨드 등록 완료 (sync는 on_ready에서 실행)")


bot = JongminiBot()


@bot.event
async def on_ready():
    logger.info(f"종미니 봇 로그인 성공: {bot.user}")
    print(f"종미니 봇 로그인 성공: {bot.user}")

    # 슬래시 명령어 동기화 (최초 1회만)
    if not hasattr(bot, '_commands_synced'):
        await bot.tree.sync()
        logger.info("슬래시 명령어 동기화 완료")
        bot._commands_synced = True

    # 현재 시간과 타임존 로그 출력
    now = datetime.now(tz=bot.scheduler.timezone)
    logger.info(f"현재 시간: {now.isoformat()} (타임존: {bot.scheduler.timezone})")
    print(f"현재 시간: {now.isoformat()} (타임존: {bot.scheduler.timezone})")

    # 기존 알림 task
    if not hasattr(bot, 'notify_task') or bot.notify_task.done():
        bot.notify_task = asyncio.create_task(periodic_notify(bot, GUILD_ID))
        logger.info("타임라인 아이템 알림 task 시작됨")

    # 신규 일간 집계 task
    if not hasattr(bot, 'daily_aggregation_task') or bot.daily_aggregation_task.done():
        bot.daily_aggregation_task = asyncio.create_task(daily_aggregation_task(bot, GUILD_ID))
        logger.info("일간 모험단 집계 task 시작됨")

    # 주간 집계 task
    if not hasattr(bot, 'weekly_aggregation_task') or bot.weekly_aggregation_task.done():
        bot.weekly_aggregation_task = asyncio.create_task(weekly_aggregation_task(bot, GUILD_ID))
        logger.info("주간 모험단 집계 task 시작됨")

    # 월간 집계 task
    if not hasattr(bot, 'monthly_aggregation_task') or bot.monthly_aggregation_task.done():
        bot.monthly_aggregation_task = asyncio.create_task(monthly_aggregation_task(bot, GUILD_ID))
        logger.info("월간 모험단 집계 task 시작됨")

    # 경매장 시세 폴링 task (실시간 알림 포함)
    if not hasattr(bot, 'auction_poll_task') or bot.auction_poll_task.done():
        bot.auction_poll_task = asyncio.create_task(poll_auction_prices(bot, GUILD_ID))
        logger.info("경매장 시세 폴링 task 시작됨")

    # APScheduler 스케줄러 시작 및 작업 등록
    if not bot.scheduler.running:
        bot.scheduler.start()
        logger.info("스케줄러 시작됨")

    # 스케줄러 타임존 변수
    bot.scheduler.timezone

    # 캐릭터별 주간 집계: 매주 목요일 05:59 실행
    # bot.scheduler.add_job(
    #    aggregate_weekly_items_by_character,
    #    trigger=CronTrigger(day_of_week="thu", hour=5, minute=59),
    #    args=[bot, GUILD_ID],
    #    id="weekly_character_aggregation_job",
    #    replace_existing=True
    # )
    # logger.info("캐릭터별 주간 집계 작업 스케줄 등록됨 (매주 목요일 05:59)")


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    logger.info(f"메시지 수신: 채널 ID={message.channel.id}, 작성자={message.author.display_name}, 내용='{message.content}'")

    # process commands first
    await bot.process_commands(message)

    # then handle with moderator
    # await bot.chat_moderator.handle_message(message)


bot.run(TOKEN)
