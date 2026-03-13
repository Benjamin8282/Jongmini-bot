import discord
from discord import app_commands, Interaction
from core.db import save_typed_output_channel, get_all_output_channels
from core.logger import logger


class NotificationChannelView(discord.ui.View):
    def __init__(self, guild_id: str):
        super().__init__(timeout=120)
        self.guild_id = guild_id

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="아이템 알림 채널 선택",
        channel_types=[discord.ChannelType.text, discord.ChannelType.news],
        min_values=1, max_values=1,
        row=0
    )
    async def item_channel_select(self, interaction: Interaction, select: discord.ui.ChannelSelect):
        channel = select.values[0]
        await save_typed_output_channel(self.guild_id, 'item', str(channel.id))
        logger.info(f"아이템 알림 채널 설정: guild={self.guild_id}, channel={channel.id}")

        # 현재 설정 갱신 표시
        settings = await get_all_output_channels(self.guild_id)
        embed = build_settings_embed(settings)
        embed.set_footer(text=f"아이템 알림 채널이 #{channel.name}(으)로 설정되었습니다.")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="경제 알림 채널 선택",
        channel_types=[discord.ChannelType.text, discord.ChannelType.news],
        min_values=1, max_values=1,
        row=1
    )
    async def economy_channel_select(self, interaction: Interaction, select: discord.ui.ChannelSelect):
        channel = select.values[0]
        await save_typed_output_channel(self.guild_id, 'economy', str(channel.id))
        logger.info(f"경제 알림 채널 설정: guild={self.guild_id}, channel={channel.id}")

        # 현재 설정 갱신 표시
        settings = await get_all_output_channels(self.guild_id)
        embed = build_settings_embed(settings)
        embed.set_footer(text=f"경제 알림 채널이 #{channel.name}(으)로 설정되었습니다.")
        await interaction.response.edit_message(embed=embed, view=self)


def build_settings_embed(settings: dict | None) -> discord.Embed:
    embed = discord.Embed(
        title="알림 채널 설정",
        description="아이템 알림과 경제 알림을 각각 다른 채널로 보낼 수 있습니다.\n"
                    "아래 드롭다운에서 원하는 채널을 선택하세요.",
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


@app_commands.command(name="출력채널", description="아이템/경제 알림 출력 채널을 각각 설정합니다")
async def set_output_channel(interaction: Interaction):
    guild_id = str(interaction.guild_id)
    logger.info(f"/출력채널 명령 호출됨: guild_id={guild_id}, user={interaction.user.id}")

    try:
        settings = await get_all_output_channels(guild_id)
        embed = build_settings_embed(settings)
        view = NotificationChannelView(guild_id)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    except Exception as e:
        logger.error(f"출력채널 커맨드 실패: guild_id={guild_id}, error={e}")
        await interaction.response.send_message(
            "알림 채널 설정 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.", ephemeral=True
        )
