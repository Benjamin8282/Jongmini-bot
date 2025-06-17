# main.py
import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# 환경 변수 로딩 (.env에 DISCORD_TOKEN 있어야 함)
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# 봇 클래스 정의
class JongminiBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.default())

    async def setup_hook(self):
        await self.tree.sync()  # 슬래시 커맨드 Discord 서버에 동기화
        print("📡 슬래시 커맨드 동기화 완료")

# 봇 인스턴스 생성
bot = JongminiBot()

# 슬래시 커맨드 정의: /hello
@bot.tree.command(name="hello", description="종미니가 인사해요")
async def hello_command(interaction: discord.Interaction):
    await interaction.response.send_message("안녕하세요! 저는 섭종미니예요 👋")

# 봇 준비 완료 시 출력
@bot.event
async def on_ready():
    print(f"✅ 종미니 봇 로그인 성공: {bot.user}")

# 봇 실행
bot.run(TOKEN)
