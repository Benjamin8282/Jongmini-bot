import discord
from discord import app_commands, Interaction, ui

from core.db import (
    add_watch_item,
    remove_watch_item,
    get_all_watch_items,
)
from core.dnf_api import fetch_item_search, fetch_auction_sold
from core.logger import logger
from tasks.poll_auction_prices import fetch_and_save_item_prices

ITEM_IMAGE_URL = "https://img-api.neople.co.kr/df/items/{item_id}"


class ItemSelectView(ui.View):
    """아이템 검색 결과에서 선택하는 UI (이미지 포함)"""
    def __init__(self, items: list[dict], author_id: int):
        super().__init__(timeout=60)
        self.selected_item = None
        self.author_id = author_id
        self._items_map = {
            item["itemId"]: item for item in items[:25]
        }

        options = [
            discord.SelectOption(
                label=item["itemName"][:100],
                description=(
                    f'{item.get("itemRarity", "")} | '
                    f'{item.get("itemType", "")} / {item.get("itemTypeDetail", "")}'
                ),
                value=item["itemId"]
            ) for item in items[:25]
        ]

        self.select = ui.Select(
            placeholder="감시할 아이템을 선택하세요",
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

        item_id = self.select.values[0]
        self.selected_item = self._items_map[item_id]
        item = self.selected_item

        embed = discord.Embed(
            title=item["itemName"],
            description=(
                f"등급: {item.get('itemRarity', '알 수 없음')}\n"
                f"분류: {item.get('itemType', '')} / {item.get('itemTypeDetail', '')}"
            ),
            color=0x2ECC71
        )
        embed.set_thumbnail(url=ITEM_IMAGE_URL.format(item_id=item_id))

        await interaction.response.send_message(
            content=f"'{item['itemName']}' 시세 추적을 등록합니다.",
            embed=embed,
            ephemeral=True
        )
        self.stop()


class WatchItemRemoveSelect(ui.View):
    """감시 해제할 아이템 선택 UI"""
    PAGE_SIZE = 25

    def __init__(self, items: list[dict], author_id: int, page: int = 0):
        super().__init__(timeout=60)
        self.selected_item = None
        self.author_id = author_id
        self.all_items = items
        self.page = page
        self._items_map = {}
        self._build()

    def _build(self):
        self.clear_items()
        start = self.page * self.PAGE_SIZE
        page_items = self.all_items[start:start + self.PAGE_SIZE]

        self._items_map = {
            item["item_id"]: item for item in page_items
        }

        options = [
            discord.SelectOption(
                label=item["item_name"][:100],
                value=item["item_id"]
            ) for item in page_items
        ]

        self.select = ui.Select(
            placeholder="해제할 아이템을 선택하세요",
            options=options
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

        total_pages = (len(self.all_items) + self.PAGE_SIZE - 1) // self.PAGE_SIZE
        if total_pages > 1:
            prev_btn = ui.Button(
                label="◀ 이전", style=discord.ButtonStyle.secondary,
                disabled=self.page == 0, row=1
            )
            prev_btn.callback = self._prev_callback
            self.add_item(prev_btn)

            page_label = ui.Button(
                label=f"{self.page + 1}/{total_pages}",
                style=discord.ButtonStyle.secondary, disabled=True, row=1
            )
            self.add_item(page_label)

            next_btn = ui.Button(
                label="다음 ▶", style=discord.ButtonStyle.secondary,
                disabled=self.page >= total_pages - 1, row=1
            )
            next_btn.callback = self._next_callback
            self.add_item(next_btn)

    async def _prev_callback(self, interaction: Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "본인이 실행한 명령어만 응답할 수 있습니다.", ephemeral=True)
            return
        self.page = max(0, self.page - 1)
        self._build()
        await interaction.response.edit_message(view=self)

    async def _next_callback(self, interaction: Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "본인이 실행한 명령어만 응답할 수 있습니다.", ephemeral=True)
            return
        total_pages = (len(self.all_items) + self.PAGE_SIZE - 1) // self.PAGE_SIZE
        self.page = min(total_pages - 1, self.page + 1)
        self._build()
        await interaction.response.edit_message(view=self)

    async def select_callback(self, interaction: Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "본인이 실행한 명령어만 응답할 수 있습니다.", ephemeral=True
            )
            return

        item_id = self.select.values[0]
        self.selected_item = self._items_map[item_id]
        await interaction.response.send_message(
            f"'{self.selected_item['item_name']}' 시세 추적을 해제합니다.",
            ephemeral=True
        )
        self.stop()


async def _build_item_embeds(items: list[dict]) -> list[discord.Embed]:
    """검색된 아이템 목록을 이미지 포함 embed 리스트로 변환"""
    embeds = []
    for idx, item in enumerate(items[:10]):  # Discord embed 최대 10개
        embed = discord.Embed(
            title=f"{idx + 1}. {item['itemName']}",
            description=(
                f"등급: {item.get('itemRarity', '알 수 없음')}\n"
                f"분류: {item.get('itemType', '')} / {item.get('itemTypeDetail', '')}"
            ),
            color=_rarity_color(item.get("itemRarity", ""))
        )
        embed.set_thumbnail(
            url=ITEM_IMAGE_URL.format(item_id=item["itemId"])
        )
        embeds.append(embed)
    return embeds


def _rarity_color(rarity: str) -> int:
    mapping = {
        "커먼": 0x888888,
        "언커먼": 0x68D5ED,
        "레어": 0xB36BFF,
        "유니크": 0xFF00FF,
        "에픽": 0xFFB400,
        "레전더리": 0xFF7800,
        "태초": 0x58D3DC,
    }
    return mapping.get(rarity, 0x888888)


def _filter_by_tradeable(items: list[dict], sold_data: list[dict] | None) -> list[dict]:
    """거래 기록이 있는 아이템만 필터링."""
    if not sold_data:
        return items
    tradeable_ids = {row["itemId"] for row in sold_data}
    return [item for item in items if item["itemId"] in tradeable_ids]


async def _search_tradeable_items(item_name: str) -> list[dict] | None:
    """아이템 검색 후 거래 가능한 아이템만 필터링. None이면 검색 결과 없음."""
    items = await fetch_item_search(item_name)
    if not items:
        return None
    items = _filter_by_tradeable(items, await fetch_auction_sold(item_name))
    return items or None


async def _register_single_item(interaction: Interaction, item: dict, embeds: list[discord.Embed]):
    """단일 검색 결과 아이템을 바로 등록."""
    is_new = await add_watch_item(item["itemId"], item["itemName"], interaction.user.id)
    if is_new:
        count = await fetch_and_save_item_prices(item["itemId"], item["itemName"])
        embeds[0].set_footer(text=f"시세 추적 등록 완료 | 최초 수집: {count or 0}건")
        await interaction.followup.send(
            content=f"'{item['itemName']}' 시세 추적을 시작합니다.",
            embed=embeds[0]
        )
    else:
        await interaction.followup.send(
            f"'{item['itemName']}'은(는) 이미 추적 중인 아이템입니다."
        )


async def _register_selected_item(interaction: Interaction, item: dict):
    """사용자가 선택한 아이템을 등록."""
    is_new = await add_watch_item(item["itemId"], item["itemName"], interaction.user.id)
    if is_new:
        count = await fetch_and_save_item_prices(item["itemId"], item["itemName"])
        await interaction.followup.send(
            f"'{item['itemName']}' 시세 추적 등록 완료 (최초 수집: {count or 0}건)",
            ephemeral=True
        )
    else:
        await interaction.followup.send(
            f"'{item['itemName']}'은(는) 이미 추적 중인 아이템입니다.",
            ephemeral=True
        )


@app_commands.command(name="시세등록", description="경매장 시세를 추적할 아이템을 등록합니다")
@app_commands.describe(item_name="추적할 아이템 이름 (부분 입력 가능)")
async def auction_watch_register(interaction: Interaction, item_name: str):
    logger.info(f"/시세등록 호출: 사용자={interaction.user.id}, 아이템={item_name}")
    await interaction.response.defer(thinking=True)

    items = await _search_tradeable_items(item_name)
    if not items:
        await interaction.followup.send("경매장에서 거래 가능한 아이템이 없습니다.")
        return

    embeds = await _build_item_embeds(items)

    if len(items) == 1:
        await _register_single_item(interaction, items[0], embeds)
        return

    view = ItemSelectView(items, interaction.user.id)
    await interaction.followup.send(
        content=f"{len(items)}개의 아이템이 검색되었습니다. 아래에서 선택해주세요.",
        embeds=embeds, view=view, ephemeral=True
    )

    await view.wait()
    if view.selected_item:
        await _register_selected_item(interaction, view.selected_item)


@app_commands.command(name="시세해제", description="시세 추적 중인 아이템을 해제합니다")
async def auction_watch_unregister(interaction: Interaction):
    logger.info(f"/시세해제 호출: 사용자={interaction.user.id}")
    await interaction.response.defer(thinking=True)

    items = await get_all_watch_items()
    if not items:
        await interaction.followup.send("등록된 시세 추적 아이템이 없습니다.")
        return

    view = WatchItemRemoveSelect(items, interaction.user.id)
    await interaction.followup.send(
        "해제할 아이템을 선택하세요.",
        view=view,
        ephemeral=True
    )

    await view.wait()
    if view.selected_item:
        await remove_watch_item(view.selected_item["item_id"])


class WatchItemListView(ui.View):
    """시세 목록 페이지네이션 UI"""
    PAGE_SIZE = 10  # Discord embed 최대 10개

    def __init__(self, items: list[dict], author_id: int):
        super().__init__(timeout=120)
        self.all_items = items
        self.author_id = author_id
        self.page = 0
        self._build_buttons()

    @property
    def total_pages(self) -> int:
        return (len(self.all_items) + self.PAGE_SIZE - 1) // self.PAGE_SIZE

    def _page_embeds(self) -> list[discord.Embed]:
        start = self.page * self.PAGE_SIZE
        page_items = self.all_items[start:start + self.PAGE_SIZE]
        embeds = []
        for item in page_items:
            registered_at = (item.get("registered_at") or "알 수 없음")[:10]
            embed = discord.Embed(
                title=item["item_name"],
                description=f"등록일: {registered_at}",
                color=0x3498DB
            )
            embed.set_thumbnail(
                url=ITEM_IMAGE_URL.format(item_id=item["item_id"])
            )
            embeds.append(embed)
        return embeds

    def _page_content(self) -> str:
        total = len(self.all_items)
        if self.total_pages <= 1:
            return f"시세 추적 중인 아이템 ({total}개)"
        return f"시세 추적 중인 아이템 ({total}개) — {self.page + 1}/{self.total_pages} 페이지"

    def _build_buttons(self):
        self.clear_items()
        if self.total_pages <= 1:
            return
        prev_btn = ui.Button(
            label="◀ 이전", style=discord.ButtonStyle.secondary,
            disabled=self.page == 0
        )
        prev_btn.callback = self._prev_callback
        self.add_item(prev_btn)

        page_label = ui.Button(
            label=f"{self.page + 1}/{self.total_pages}",
            style=discord.ButtonStyle.secondary, disabled=True
        )
        self.add_item(page_label)

        next_btn = ui.Button(
            label="다음 ▶", style=discord.ButtonStyle.secondary,
            disabled=self.page >= self.total_pages - 1
        )
        next_btn.callback = self._next_callback
        self.add_item(next_btn)

    async def _prev_callback(self, interaction: Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "본인이 실행한 명령어만 응답할 수 있습니다.", ephemeral=True)
            return
        self.page = max(0, self.page - 1)
        self._build_buttons()
        await interaction.response.edit_message(
            content=self._page_content(), embeds=self._page_embeds(), view=self)

    async def _next_callback(self, interaction: Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "본인이 실행한 명령어만 응답할 수 있습니다.", ephemeral=True)
            return
        self.page = min(self.total_pages - 1, self.page + 1)
        self._build_buttons()
        await interaction.response.edit_message(
            content=self._page_content(), embeds=self._page_embeds(), view=self)


@app_commands.command(name="시세목록", description="현재 시세 추적 중인 아이템 목록을 조회합니다")
async def auction_watch_list(interaction: Interaction):
    logger.info(f"/시세목록 호출: 사용자={interaction.user.id}")

    items = await get_all_watch_items()
    if not items:
        await interaction.response.send_message("등록된 시세 추적 아이템이 없습니다.")
        return

    view = WatchItemListView(items, interaction.user.id)
    await interaction.response.send_message(
        content=view._page_content(),
        embeds=view._page_embeds(),
        view=view if view.total_pages > 1 else None
    )
