import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from core.dnf_api import preload_item_cache
from core.dundam_queue import DundamQueueManager
from core.logger import logger
import discord
from core.chat_moderator import ChatModerator
from discord.ext import commands
from dotenv import load_dotenv
from core.db import init_db

# tasks import
from tasks.daily_aggregation import daily_aggregation_task
from tasks.monthly_aggregation import monthly_aggregation_task
from tasks.notify_items import periodic_notify, catchup_code550
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
from commands.auction_compare import auction_compare
from commands.auction_overview import auction_overview
from commands.activity_basket import (
    basket_register, basket_unregister, basket_list, activity_index_cmd
)
from commands.alert_settings import (
    alert_settings_cmd, alert_list_cmd, alert_remove_cmd
)
from commands.dunspy import dunspy_cmd
from commands.avatar_search import avatar_search
from commands.avatar_price import avatar_price
from commands.export_data import export_data
from commands.rest_days import rest_days_cmd

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")  # 디폴트 값 설정


def get_scheduler_timezone():
    # UTC 고정
    utc_tz = ZoneInfo("Asia/Seoul")  # KST로 설정
    logger.info(f"스케줄러 타임존으로 KST 고정: {utc_tz}")
    return utc_tz


# 백그라운드 task 정의: (속성명, 팩토리 함수, 로그 메시지)
_BACKGROUND_TASKS = [
    ("notify_task", lambda b, g: periodic_notify(b, g), "타임라인 아이템 알림 task 시작됨"),
    ("daily_aggregation_task", lambda b, g: daily_aggregation_task(b, g), "일간 모험단 집계 task 시작됨"),
    ("weekly_aggregation_task", lambda b, g: weekly_aggregation_task(b, g), "주간 모험단 집계 task 시작됨"),
    ("monthly_aggregation_task", lambda b, g: monthly_aggregation_task(b, g), "월간 모험단 집계 task 시작됨"),
    ("auction_poll_task", lambda b, g: poll_auction_prices(b, g), "경매장 시세 폴링 task 시작됨"),
]


def _should_start_task(bot, attr_name):
    """task 속성이 없거나 완료된 경우 True 반환"""
    return not hasattr(bot, attr_name) or getattr(bot, attr_name).done()


def _ensure_background_tasks(bot, guild_id):
    """필요한 백그라운드 task들을 시작"""
    for attr_name, factory, log_msg in _BACKGROUND_TASKS:
        if _should_start_task(bot, attr_name):
            setattr(bot, attr_name, asyncio.create_task(factory(bot, guild_id)))
            logger.info(log_msg)


async def _sync_guild_commands(bot):
    """길드별 슬래시 명령어 동기화 (최초 1회)"""
    if hasattr(bot, '_commands_synced'):
        return
    for guild in bot.guilds:
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        cmd_names = [c.name for c in synced]
        logger.info(f"슬래시 명령어 길드 동기화 완료: {guild.name} ({guild.id}) - {len(synced)}개: {cmd_names}")
    # 기존 글로벌 커맨드 제거 (중복 방지)
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()
    logger.info("글로벌 커맨드 정리 완료")
    bot._commands_synced = True


class JongminiBot(commands.Bot):
    def __init__(self):
        scheduler_tz = get_scheduler_timezone()
        self.scheduler = AsyncIOScheduler(timezone=scheduler_tz)

        intents = discord.Intents.default()
        intents.messages = True
        intents.message_content = True

        super().__init__(command_prefix="!", intents=intents)
        self.chat_moderator = ChatModerator()
        self.dundam_queue = DundamQueueManager.get_instance()
        logger.info("JongminiBot 인스턴스 생성됨")

    async def close(self):
        """봇 종료 시 리소스 정리."""
        from core.db import close_db
        from core.dnf_api import close_session
        await close_session()
        await close_db()
        logger.info("봇 리소스 정리 완료")
        await super().close()

    async def setup_hook(self):
        logger.info("봇 setup_hook 시작 - DB 초기화 및 명령어 등록")
        await init_db()
        logger.info("DB 초기화 완료")
        await preload_item_cache()
        from core.avatar_market_api import preload_caches as preload_avatar_caches
        await preload_avatar_caches()

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
        self.tree.add_command(auction_compare)
        self.tree.add_command(auction_overview)
        self.tree.add_command(basket_register)
        self.tree.add_command(basket_unregister)
        self.tree.add_command(basket_list)
        self.tree.add_command(activity_index_cmd)
        self.tree.add_command(alert_settings_cmd)
        self.tree.add_command(alert_list_cmd)
        self.tree.add_command(alert_remove_cmd)
        self.tree.add_command(dunspy_cmd)
        self.tree.add_command(avatar_search)
        self.tree.add_command(avatar_price)
        self.tree.add_command(export_data)
        self.tree.add_command(rest_days_cmd)
        logger.info("커맨드 등록 완료 (sync는 on_ready에서 실행)")


bot = JongminiBot()


@bot.event
async def on_ready():
    logger.info(f"종미니 봇 로그인 성공: {bot.user}")
    print(f"종미니 봇 로그인 성공: {bot.user}")

    # 슬래시 명령어 동기화 (최초 1회만)
    await _sync_guild_commands(bot)

    # 현재 시간과 타임존 로그 출력
    now = datetime.now(tz=bot.scheduler.timezone)
    logger.info(f"현재 시간: {now.isoformat()} (타임존: {bot.scheduler.timezone})")
    print(f"현재 시간: {now.isoformat()} (타임존: {bot.scheduler.timezone})")

    # [1회성] code 550 누락 데이터 캐치업 (배포 후 제거)
    if not hasattr(bot, '_catchup_done'):
        bot._catchup_done = True
        await catchup_code550(bot, GUILD_ID)

    # 백그라운드 task 시작
    _ensure_background_tasks(bot, GUILD_ID)

    # 던담 큐 매니저 시작
    await bot.dundam_queue.start()

    # APScheduler 스케줄러 시작 및 작업 등록
    if not bot.scheduler.running:
        bot.scheduler.start()
        logger.info("스케줄러 시작됨")

    # 던담 API 일일 사용량 자정(KST) 리셋 — 별도 리셋 불필요 (날짜별 카운트)
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
