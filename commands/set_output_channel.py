from discord import app_commands, Interaction
from core.db import save_output_channel
from core.logger import logger

@app_commands.command(name="출력", description="이 서버에서 아이템 알림을 출력할 채널을 등록합니다")
async def set_output_channel(interaction: Interaction):
    guild_id = str(interaction.guild_id)
    channel_id = str(interaction.channel_id)

    logger.info(f"/출력 명령 호출됨: guild_id={guild_id}, channel_id={channel_id}, user={interaction.user.id}")

    try:
        await save_output_channel(guild_id, channel_id)
        logger.info(f"출력 채널 저장 성공: guild_id={guild_id}, channel_id={channel_id}")
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(
            f"이제부터 이 채널(<#{channel_id}>)에 아이템 알림이 출력됩니다!", ephemeral=True
        )
    except Exception as e:
        logger.error(f"출력 채널 저장 실패: guild_id={guild_id}, channel_id={channel_id}, error={e}")
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(
            "출력 채널 등록 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.", ephemeral=True
        )
