import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from core.db import init_db
from commands.total import total_command

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

class JongminiBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.default())

    async def setup_hook(self):
        # ✅ DB 초기화
        await init_db()

        # 명령어 등록
        from commands.hello import hello_command
        from commands.register import register_command

        # noinspection PyTypeChecker
        self.tree.add_command(hello_command)
        # noinspection PyTypeChecker
        self.tree.add_command(register_command)
        # noinspection PyTypeChecker
        self.tree.add_command(total_command)

        await self.tree.sync()
        print(self.tree.get_commands())
        print("📡 슬래시 커맨드 동기화 완료")

bot = JongminiBot()

@bot.event
async def on_ready():
    print(f"✅ 종미니 봇 로그인 성공: {bot.user}")

bot.run(TOKEN)
