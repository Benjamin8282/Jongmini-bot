import asyncio

import discord
from discord import app_commands, Interaction

from core.dunspy_index import calc_dunspy_index
from core.chart import generate_dunspy_chart
from core.logger import logger

PERIODS = [
    {"label": "7일", "days": 7},
    {"label": "14일", "days": 14},
    {"label": "30일", "days": 30},
    {"label": "60일", "days": 60},
    {"label": "90일", "days": 90},
]


def _build_index_embed(data: dict, display_days: int) -> discord.Embed:
    change = data["change"]
    change_pct = data["change_pct"]
    arrow = "▲" if change > 0 else "▼" if change < 0 else "−"
    color = 0xE74C3C if change > 0 else 0x3498DB if change < 0 else 0x95A5A6

    embed = discord.Embed(
        title="DUNSPY 던스피 종합지수",
        description=(
            f"**{data['current']:,.2f}**  "
            f"{arrow} {abs(change):.2f} ({abs(change_pct):.2f}%)"
        ),
        color=color,
    )
    embed.add_field(
        name="전일 종가", value=f"{data['prev_close']:,.2f}", inline=True
    )
    embed.add_field(
        name="기간 고가", value=f"{data['high']:,.2f}", inline=True
    )
    embed.add_field(
        name="기간 저가", value=f"{data['low']:,.2f}", inline=True
    )
    embed.add_field(
        name="구성 종목", value=f"{data['item_count']}개", inline=True
    )
    embed.add_field(
        name="기준일", value=data["base_date"], inline=True
    )
    embed.add_field(
        name="조회 기간", value=f"{display_days}일", inline=True
    )
    embed.set_image(url="attachment://dunspy.png")
    return embed


def _format_component_line(c: dict) -> str:
    """종목 한 줄 포맷."""
    arrow = "▲" if c["change_pct"] > 0 else "▼" if c["change_pct"] < 0 else "−"
    icon = "🔴" if c["change_pct"] > 0 else "🔵" if c["change_pct"] < 0 else "⚪"
    return (
        f"{icon} **{c['name']}** "
        f"{int(c['price']):,}G "
        f"({arrow}{abs(c['change_pct']):.2f}%)"
    )


def _build_component_embed(components: list[dict]) -> discord.Embed | None:
    if not components:
        return None
    lines = [_format_component_line(c) for c in components[:15]]
    embed = discord.Embed(
        title="종목별 등락",
        description="\n".join(lines),
        color=0x2C3E50,
    )
    embed.set_footer(text="전일 대비 변동률 기준 정렬")
    return embed


async def _build_dunspy(display_days: int = 30):
    """던스피 지수 계산 + 차트 생성. (embed, file) 또는 에러 str 반환."""
    data = await calc_dunspy_index(display_days=display_days)
    if data is None:
        return "바스켓 아이템이 부족하거나 가격 데이터가 없습니다."

    chart_buf = await asyncio.to_thread(
        generate_dunspy_chart,
        dates=data["dates"],
        index_values=data["index"],
        current=data["current"],
        change=data["change"],
        change_pct=data["change_pct"],
        item_count=data["item_count"],
        base_date=data["base_date"],
    )
    if not chart_buf:
        return "차트 생성에 실패했습니다."

    file = discord.File(chart_buf, filename="dunspy.png")
    embed = _build_index_embed(data, display_days)
    comp_embed = _build_component_embed(data.get("components", []))
    return embed, file, comp_embed


class DunspyControlView(discord.ui.View):
    """던스피 기간 조절 버튼 View"""
    def __init__(self, display_days: int = 30):
        super().__init__(timeout=300)
        self.display_days = display_days
        self.message = None
        self._update_buttons()

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.delete()
            except discord.HTTPException:
                pass

    def _update_buttons(self):
        self.clear_items()
        for p in PERIODS:
            active = p["days"] == self.display_days
            btn = discord.ui.Button(
                label=p["label"],
                style=(discord.ButtonStyle.primary if active
                       else discord.ButtonStyle.secondary),
                custom_id=f"dunspy_pd_{p['days']}",
                row=0,
            )
            btn.callback = self._make_callback(p["days"])
            self.add_item(btn)

    def _make_callback(self, days: int):
        async def callback(interaction: Interaction):
            self.display_days = days
            await self._refresh(interaction)
        return callback

    async def _refresh(self, interaction: Interaction):
        await interaction.response.defer()
        self._update_buttons()

        result = await _build_dunspy(self.display_days)
        if isinstance(result, str):
            await interaction.edit_original_response(
                content=result, embeds=[], attachments=[], view=self
            )
        else:
            embed, file, comp_embed = result
            embeds = [embed]
            if comp_embed:
                embeds.append(comp_embed)
            await interaction.edit_original_response(
                content=None, embeds=embeds, attachments=[file], view=self
            )


@app_commands.command(
    name="던스피",
    description="던스피(DUNSPY) 종합지수 - 바스켓 아이템 기반 시장 대표 지수"
)
async def dunspy_cmd(interaction: Interaction):
    logger.info(f"/던스피 호출: 사용자={interaction.user.id}")
    await interaction.response.defer(thinking=True)

    view = DunspyControlView(display_days=30)
    result = await _build_dunspy(30)

    if isinstance(result, str):
        msg = await interaction.followup.send(content=result, view=view)
    else:
        embed, file, comp_embed = result
        embeds = [embed]
        if comp_embed:
            embeds.append(comp_embed)
        msg = await interaction.followup.send(
            embeds=embeds, file=file, view=view
        )
    view.message = msg
