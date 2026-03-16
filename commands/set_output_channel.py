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


def _truncate_label(label: str, max_len: int = 100) -> str:
    return label[:max_len - 3] + "..." if len(label) > max_len else label


async def channel_autocomplete(
    interaction: Interaction, current: str
) -> list[app_commands.Choice[str]]:
    channels = _get_messageable_channels(interaction.guild)
    if current:
        channels = [ch for ch in channels if current.lower() in ch.name.lower()]
    return [
        app_commands.Choice(name=_truncate_label(f"#{ch.name}"), value=str(ch.id))
        for ch in channels[:25]
    ]


def _channel_display(channel_id: str | None, default_id: str | None) -> str:
    if channel_id:
        return f"<#{channel_id}>"
    if default_id:
        return f"<#{default_id}> (기본)"
    return "미설정"


def build_settings_embed(settings: dict | None) -> discord.Embed:
    embed = discord.Embed(
        title="알림 채널 설정",
        description="아이템 알림과 경제 알림을 각각 다른 채널로 보낼 수 있습니다.",
        color=0x3498db
    )

    default_ch = settings.get('channel_id') if settings else None
    item_ch = settings.get('item_channel_id') if settings else None
    economy_ch = settings.get('economy_channel_id') if settings else None

    embed.add_field(
        name="아이템 알림 채널",
        value=f"{_channel_display(item_ch, default_ch)}\n실시간 득템, 일간/주간/월간 랭킹",
        inline=True
    )
    embed.add_field(
        name="경제 알림 채널",
        value=f"{_channel_display(economy_ch, default_ch)}\n시세 변동, 모닝 브리핑",
        inline=True
    )

    return embed


async def _save_channel(guild: discord.Guild, guild_id: str, channel_id_str: str, channel_type: str) -> str | None:
    """채널을 저장하고 결과 메시지를 반환. 채널이 없으면 None."""
    channel = guild.get_channel(int(channel_id_str))
    if not channel:
        return None
    type_labels = {"item": "아이템", "economy": "경제"}
    await save_typed_output_channel(guild_id, channel_type, channel_id_str)
    label = type_labels[channel_type]
    logger.info(f"{label} 알림 채널 설정: guild={guild_id}, channel={channel_id_str}")
    return f"{label} 알림 → <#{channel_id_str}>"


def _any_channel_specified(아이템, 경제):
    return 아이템 is not None or 경제 is not None


async def _show_current_settings(interaction: Interaction, guild_id: str):
    """현재 채널 설정을 조회하여 표시."""
    settings = await get_all_output_channels(guild_id)
    embed = build_settings_embed(settings)
    embed.set_footer(text="사용법: /출력채널 아이템:채널명 경제:채널명")
    await interaction.response.send_message(embed=embed, ephemeral=True)


async def _save_channels(
    interaction: Interaction, guild_id: str, 아이템: str | None, 경제: str | None
) -> list[str] | None:
    """채널 저장 처리. 실패 시 None (응답 전송 포함)."""
    results = []
    for channel_id_str, ch_type in [(아이템, "item"), (경제, "economy")]:
        if channel_id_str is None:
            continue
        msg = await _save_channel(interaction.guild, guild_id, channel_id_str, ch_type)
        if msg is None:
            label = "아이템" if ch_type == "item" else "경제"
            await interaction.response.send_message(
                f"{label} 알림 채널을 찾을 수 없습니다.", ephemeral=True
            )
            return None
        results.append(msg)
    return results


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
        if not _any_channel_specified(아이템, 경제):
            await _show_current_settings(interaction, guild_id)
            return

        results = await _save_channels(interaction, guild_id, 아이템, 경제)
        if results is None:
            return

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
