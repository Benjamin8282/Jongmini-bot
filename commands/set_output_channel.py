import discord
from discord import app_commands, Interaction
from core.db import save_typed_output_channel, get_all_output_channels
from core.logger import logger

MESSAGEABLE_TYPES = {
    discord.ChannelType.text,
    discord.ChannelType.news,
    discord.ChannelType.voice,
    discord.ChannelType.public_thread,
    discord.ChannelType.private_thread,
    discord.ChannelType.news_thread,
}


def _get_messageable_channels(guild: discord.Guild) -> list[discord.abc.GuildChannel]:
    return [ch for ch in guild.channels if ch.type in MESSAGEABLE_TYPES]


async def channel_autocomplete(
    interaction: Interaction, current: str
) -> list[app_commands.Choice[str]]:
    channels = _get_messageable_channels(interaction.guild)
    if current:
        channels = [ch for ch in channels if current.lower() in ch.name.lower()]
    choices = []
    for ch in channels[:25]:
        label = f"#{ch.name}"
        if len(label) > 100:
            label = label[:97] + "..."
        choices.append(app_commands.Choice(name=label, value=str(ch.id)))
    return choices


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
    아이템="아이템 알림을 보낼 채널 (채널명 입력하여 검색)",
    경제="경제 알림을 보낼 채널 (채널명 입력하여 검색)"
)
@app_commands.autocomplete(아이템=channel_autocomplete, 경제=channel_autocomplete)
async def set_output_channel(
    interaction: Interaction,
    아이템: str = None,
    경제: str = None
):
    guild_id = str(interaction.guild_id)
    logger.info(f"/출력채널 명령 호출됨: guild_id={guild_id}, user={interaction.user.id}")

    try:
        # 파라미터 없으면 현재 설정만 표시
        if 아이템 is None and 경제 is None:
            settings = await get_all_output_channels(guild_id)
            embed = build_settings_embed(settings)
            embed.set_footer(text="사용법: /출력채널 아이템:채널명 경제:채널명")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        results = []

        if 아이템 is not None:
            channel = interaction.guild.get_channel(int(아이템))
            if not channel:
                await interaction.response.send_message("아이템 알림 채널을 찾을 수 없습니다.", ephemeral=True)
                return
            await save_typed_output_channel(guild_id, 'item', 아이템)
            results.append(f"아이템 알림 → <#{아이템}>")
            logger.info(f"아이템 알림 채널 설정: guild={guild_id}, channel={아이템}")

        if 경제 is not None:
            channel = interaction.guild.get_channel(int(경제))
            if not channel:
                await interaction.response.send_message("경제 알림 채널을 찾을 수 없습니다.", ephemeral=True)
                return
            await save_typed_output_channel(guild_id, 'economy', 경제)
            results.append(f"경제 알림 → <#{경제}>")
            logger.info(f"경제 알림 채널 설정: guild={guild_id}, channel={경제}")

        settings = await get_all_output_channels(guild_id)
        embed = build_settings_embed(settings)
        embed.set_footer(text="변경 완료: " + ", ".join(results))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    except ValueError:
        await interaction.response.send_message(
            "올바른 채널을 선택해 주세요. 채널명을 입력하면 자동완성 목록이 표시됩니다.", ephemeral=True
        )
    except Exception as e:
        logger.error(f"출력채널 커맨드 실패: guild_id={guild_id}, error={e}")
        await interaction.response.send_message(
            "알림 채널 설정 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.", ephemeral=True
        )
