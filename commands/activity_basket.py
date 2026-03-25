import asyncio

import discord
from discord import app_commands, Interaction, ui

from core.db import (
    add_basket_item, remove_basket_item, get_basket_items,
    get_all_watch_items,
)
from core.activity_index import calc_activity_index
from core.chart import generate_activity_chart
from core.logger import logger

ITEM_IMAGE_URL = "https://img-api.neople.co.kr/df/items/{item_id}"


class BasketAddSelect(ui.View):
    """시세 추적 목록에서 바스켓에 추가할 아이템 선택"""
    def __init__(self, items: list[dict], author_id: int):
        super().__init__(timeout=60)
        self.selected_item = None
        self.author_id = author_id
        self._items_map = {item["item_id"]: item for item in items[:25]}

        options = [
            discord.SelectOption(
                label=item["item_name"][:100],
                value=item["item_id"]
            ) for item in items[:25]
        ]
        self.select = ui.Select(
            placeholder="바스켓에 추가할 아이템을 선택하세요",
            options=options
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "본인이 실행한 명령어만 응답할 수 있습니다.", ephemeral=True
            )
            return
        self.selected_item = self._items_map[self.select.values[0]]
        await interaction.response.send_message(
            f"'{self.selected_item['item_name']}' 바스켓에 추가합니다.",
            ephemeral=True
        )
        self.stop()


class BasketRemoveSelect(ui.View):
    """바스켓에서 해제할 아이템 선택"""
    def __init__(self, items: list[dict], author_id: int):
        super().__init__(timeout=60)
        self.selected_item = None
        self.author_id = author_id
        self._items_map = {item["item_id"]: item for item in items[:25]}

        options = [
            discord.SelectOption(
                label=item["item_name"][:100],
                value=item["item_id"]
            ) for item in items[:25]
        ]
        self.select = ui.Select(
            placeholder="해제할 아이템을 선택하세요",
            options=options
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "본인이 실행한 명령어만 응답할 수 있습니다.", ephemeral=True
            )
            return
        self.selected_item = self._items_map[self.select.values[0]]
        await interaction.response.send_message(
            f"'{self.selected_item['item_name']}' 바스켓에서 해제합니다.",
            ephemeral=True
        )
        self.stop()


async def _get_available_items() -> tuple[list[dict] | None, str | None]:
    """바스켓 등록 가능한 아이템 목록 반환. (items, error_msg)."""
    watch_items = await get_all_watch_items()
    if not watch_items:
        return None, (
            "시세 추적 중인 아이템이 없습니다. "
            "`/시세등록`으로 먼저 아이템을 등록해주세요."
        )
    available = await _exclude_basket_items(watch_items)
    return (available, None) if available else (
        None, "시세 추적 중인 아이템이 모두 바스켓에 등록되어 있습니다."
    )


async def _exclude_basket_items(watch_items: list[dict]) -> list[dict]:
    """바스켓에 이미 등록된 아이템을 제외."""
    basket_items = await get_basket_items()
    basket_ids = {item["item_id"] for item in basket_items}
    return [i for i in watch_items if i["item_id"] not in basket_ids]


@app_commands.command(
    name="바스켓등록",
    description="시세 추적 중인 아이템을 활동지수 바스켓에 추가합니다"
)
async def basket_register(interaction: Interaction):
    logger.info(f"/바스켓등록 호출: 사용자={interaction.user.id}")
    await interaction.response.defer(thinking=True)

    available, err = await _get_available_items()
    if err:
        await interaction.followup.send(err)
        return

    view = BasketAddSelect(available, interaction.user.id)
    await interaction.followup.send(
        f"바스켓에 추가할 아이템을 선택하세요. ({len(available)}개 선택 가능)",
        view=view, ephemeral=True
    )

    await view.wait()
    if not view.selected_item:
        return

    item = view.selected_item
    is_new = await add_basket_item(
        item["item_id"], item["item_name"], interaction.user.id
    )
    if is_new:
        embed = discord.Embed(
            title=f"바스켓 등록: {item['item_name']}",
            description="활동지수 산출 바스켓에 추가되었습니다.",
            color=0x2ECC71
        )
        embed.set_thumbnail(
            url=ITEM_IMAGE_URL.format(item_id=item["item_id"])
        )
        await interaction.followup.send(embed=embed)


@app_commands.command(
    name="바스켓해제",
    description="활동지수 바스켓에서 아이템을 해제합니다"
)
async def basket_unregister(interaction: Interaction):
    logger.info(f"/바스켓해제 호출: 사용자={interaction.user.id}")
    await interaction.response.defer(thinking=True)

    items = await get_basket_items()
    if not items:
        await interaction.followup.send("바스켓에 등록된 아이템이 없습니다.")
        return

    view = BasketRemoveSelect(items, interaction.user.id)
    await interaction.followup.send(
        "해제할 아이템을 선택하세요.", view=view, ephemeral=True
    )
    await view.wait()
    if view.selected_item:
        await remove_basket_item(view.selected_item["item_id"])


@app_commands.command(
    name="바스켓목록",
    description="활동지수 바스켓 아이템 목록을 조회합니다"
)
async def basket_list(interaction: Interaction):
    logger.info(f"/바스켓목록 호출: 사용자={interaction.user.id}")

    items = await get_basket_items()
    if not items:
        await interaction.response.send_message(
            "바스켓에 등록된 아이템이 없습니다."
        )
        return

    embeds = []
    for item in items[:10]:
        added_at = (item.get("added_at") or "알 수 없음")[:10]
        embed = discord.Embed(
            title=item["item_name"],
            description=f"등록일: {added_at}",
            color=0x9B59B6
        )
        embed.set_thumbnail(
            url=ITEM_IMAGE_URL.format(item_id=item["item_id"])
        )
        embeds.append(embed)

    await interaction.response.send_message(
        content=f"활동지수 바스켓 ({len(items)}개)",
        embeds=embeds
    )


async def _send_insufficient_data(interaction: Interaction):
    """데이터 부족 시 적절한 안내 메시지 전송."""
    basket = await get_basket_items()
    if len(basket) < 3:
        await interaction.followup.send(
            f"바스켓에 최소 3개 아이템이 필요합니다. "
            f"(현재 {len(basket)}개)\n"
            f"`/바스켓등록`으로 범용 소비재를 추가해주세요."
        )
    else:
        await interaction.followup.send(
            "데이터가 부족합니다. "
            "거래량이 충분히 쌓일 때까지 기다려주세요.\n"
            "(최소 15일 이상의 거래 기록 필요)"
        )


def _status_info(current: float) -> tuple[str, int]:
    """활동지수 상태 문자열과 색상 반환."""
    if current >= 110:
        return "활발", 0xFF4757
    if current >= 90:
        return "보통", 0x2ECC71
    return "저조", 0x3498FF


def _build_activity_embed(result: dict, days: int) -> discord.Embed:
    current = result["index"][-1] if result["index"] else 0
    prev = result["index"][-2] if len(result["index"]) >= 2 else current
    diff = current - prev
    arrow = "▲" if diff > 0 else "▼" if diff < 0 else "−"
    status, color = _status_info(current)

    embed = discord.Embed(
        title="게임 활동지수",
        description=(
            f"**현재: {current:.1f}%** ({arrow} {abs(diff):.1f}%p)\n"
            f"상태: **{status}**\n\n"
            f"기간: {days}일 | 바스켓: {result['item_count']}개 아이템\n"
            f"100% = 최근 30일 평균 거래량 기준"
        ),
        color=color
    )
    embed.set_image(url="attachment://activity_index.png")
    return embed


def _add_hampel_field(embed: discord.Embed, result: dict):
    hampel = result.get("hampel_stats", {})
    if hampel.get("total_replaced", 0) <= 0:
        return
    hampel_text = f"스파이크 교체: {hampel['total_replaced']}건\n"
    item_details = ", ".join(
        f"{name}({cnt}건)"
        for name, cnt in hampel.get("items", {}).items()
    )
    if item_details:
        hampel_text += item_details
    embed.add_field(
        name="노이즈 제거 (Hampel)",
        value=hampel_text[:1024],
        inline=True
    )


def _add_changepoint_field(embed: discord.Embed, result: dict):
    changepoints = result.get("changepoints", [])
    if not changepoints:
        return
    cp_text = "\n".join(f"**{cp}**" for cp in changepoints[-3:])
    embed.add_field(
        name="체제 전환 감지 (PELT)",
        value=cp_text[:1024],
        inline=True
    )


def _add_outlier_field(embed: discord.Embed, result: dict):
    outliers = result.get("outliers", {})
    if not outliers:
        return
    recent = dict(list(outliers.items())[-3:])
    outlier_text = "\n".join(
        f"**{date}**: {', '.join(items)}"
        for date, items in recent.items()
    )
    embed.add_field(
        name="이상치 감지 (MAD)",
        value=outlier_text[:1024],
        inline=False
    )


@app_commands.command(
    name="활동지수",
    description="바스켓 아이템 거래량 기반 게임 활동지수를 조회합니다"
)
@app_commands.describe(days="조회 기간 (기본 30일)")
async def activity_index_cmd(interaction: Interaction, days: int = 30):
    logger.info(f"/활동지수 호출: 사용자={interaction.user.id}, days={days}")
    await interaction.response.defer(thinking=True)

    days = min(max(days, 7), 90)

    result = await calc_activity_index(display_days=days)
    if not result:
        await _send_insufficient_data(interaction)
        return

    chart_buf = await asyncio.to_thread(
        generate_activity_chart,
        result["dates"], result["index"], result["item_count"],
        changepoints=result.get("changepoints"),
        outlier_dates=list(result.get("outliers", {}).keys()),
        raw_index=result.get("raw_index"),
    )
    if not chart_buf:
        await interaction.followup.send("차트 생성에 실패했습니다.")
        return

    file = discord.File(chart_buf, filename="activity_index.png")
    embed = _build_activity_embed(result, days)
    _add_hampel_field(embed, result)
    _add_changepoint_field(embed, result)
    _add_outlier_field(embed, result)

    embed.set_footer(
        text=(
            "Hampel→STL→MAD→PELT 파이프라인 적용 | "
            "거래량 기반 추정치이며, 실제 접속자 수와 다를 수 있습니다."
        )
    )

    await interaction.followup.send(embed=embed, file=file)
