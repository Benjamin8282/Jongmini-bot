import asyncio
import os

from core.dnf_api import preload_item_cache
from core.logger import logger
import discord
from discord.ext import commands
from dotenv import load_dotenv
from core.db import init_db
from tasks.daily_aggregation import daily_aggregation_task
from tasks.notify_items import periodic_notify

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

class JongminiBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.default())
        logger.info("JongminiBot 인스턴스 생성됨")

    async def setup_hook(self):
        logger.info("봇 setup_hook 시작 - DB 초기화 및 명령어 등록")
        await init_db()
        logger.info("DB 초기화 완료")
        await preload_item_cache()

        from commands.hello import hello_command
        from commands.register import register_command
        from commands.total import total_command
        from commands.set_output_channel import set_output_channel
        from commands.today_status import today_status

        self.tree.add_command(hello_command)
        self.tree.add_command(register_command)
        self.tree.add_command(total_command)
        self.tree.add_command(set_output_channel)
        self.tree.add_command(today_status)

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

bot.run(TOKEN)
