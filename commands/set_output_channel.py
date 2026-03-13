import discord
from discord import app_commands, Interaction
from core.db import save_typed_output_channel, get_all_output_channels
from core.logger import logger


def build_settings_embed(settings: dict | None) -> discord.Embed:
    embed = discord.Embed(
        title="알림 채널 설정",
        description="아이템 알림과 경제 알림을 각각 다른 채널로 보낼 수 있습니다.",
        color=0x3498db
    )

    if settings:
        default_ch = settings.get('channel_id')
        item_ch = settings.get('item_channel_id')
        economy_ch = settings.get('economy_channel_id')

        item_display = f"<#{item_ch}>" if item_ch else (f"<#{default_ch}> (기본)" if default_ch else "미설정")
        economy_display = f"<#{economy_ch}>" if economy_ch else (f"<#{default_ch}> (기본)" if default_ch else "미설정")
    else:
        item_display = "미설정"
        economy_display = "미설정"

    embed.add_field(
        name="아이템 알림 채널",
        value=f"{item_display}\n실시간 득템, 일간/주간/월간 랭킹",
        inline=True
    )
    embed.add_field(
        name="경제 알림 채널",
        value=f"{economy_display}\n시세 변동, 모닝 브리핑",
        inline=True
    )

    return embed


@app_commands.command(name="출력채널", description="아이템/경제 알림 출력 채널을 각각 설정합니다 (관리자 전용)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    아이템="아이템 알림을 보낼 채널 (득템, 랭킹)",
    경제="경제 알림을 보낼 채널 (시세 변동, 모닝 브리핑)"
)
async def set_output_channel(
    interaction: Interaction,
    아이템: discord.TextChannel = None,
    경제: discord.TextChannel = None
):
    guild_id = str(interaction.guild_id)
    logger.info(f"/출력채널 명령 호출됨: guild_id={guild_id}, user={interaction.user.id}")

    try:
        # 파라미터 없으면 현재 설정만 표시
        if 아이템 is None and 경제 is None:
            settings = await get_all_output_channels(guild_id)
            embed = build_settings_embed(settings)
            embed.set_footer(text="사용법: /출력채널 아이템:#채널 경제:#채널")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        results = []

        if 아이템 is not None:
            await save_typed_output_channel(guild_id, 'item', str(아이템.id))
            results.append(f"아이템 알림 → <#{아이템.id}>")
            logger.info(f"아이템 알림 채널 설정: guild={guild_id}, channel={아이템.id}")

        if 경제 is not None:
            await save_typed_output_channel(guild_id, 'economy', str(경제.id))
            results.append(f"경제 알림 → <#{경제.id}>")
            logger.info(f"경제 알림 채널 설정: guild={guild_id}, channel={경제.id}")

        settings = await get_all_output_channels(guild_id)
        embed = build_settings_embed(settings)
        embed.set_footer(text="변경 완료: " + ", ".join(results))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    except Exception as e:
        logger.error(f"출력채널 커맨드 실패: guild_id={guild_id}, error={e}")
        await interaction.response.send_message(
            "알림 채널 설정 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.", ephemeral=True
        )
