import discord
from discord import app_commands

@app_commands.command(name="hello", description="종미니가 인사해요")
async def hello_command(interaction: discord.Interaction):
    await interaction.response.send_message("안녕하세요! 저는 섭종미니예요 👋")
