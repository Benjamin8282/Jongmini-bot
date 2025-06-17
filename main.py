import os
from core.logger import logger
import discord
from discord.ext import commands
from dotenv import load_dotenv
from core.db import init_db

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

        from commands.hello import hello_command
        from commands.register import register_command
        from commands.total import total_command

        self.tree.add_command(hello_command)
        self.tree.add_command(register_command)
        self.tree.add_command(total_command)

        await self.tree.sync()
        logger.info(f"슬래시 명령어 동기화 완료: {self.tree.get_commands()}")

bot = JongminiBot()

@bot.event
async def on_ready():
    logger.info(f"종미니 봇 로그인 성공: {bot.user}")
    print(f"✅ 종미니 봇 로그인 성공: {bot.user}")

bot.run(TOKEN)
