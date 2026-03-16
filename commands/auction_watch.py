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
    def __init__(self, items: list[dict], author_id: int):
        super().__init__(timeout=60)
        self.selected_item = None
        self.author_id = author_id
        self._items_map = {
            item["item_id"]: item for item in items[:25]
        }

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


@app_commands.command(name="시세등록", description="경매장 시세를 추적할 아이템을 등록합니다")
@app_commands.describe(item_name="추적할 아이템 이름 (부분 입력 가능)")
async def auction_watch_register(interaction: Interaction, item_name: str):
    logger.info(f"/시세등록 호출: 사용자={interaction.user.id}, 아이템={item_name}")
    await interaction.response.defer(thinking=True)

    items = await fetch_item_search(item_name)
    if not items:
        await interaction.followup.send("아이템을 찾을 수 없습니다.")
        return

    # 경매장 거래 이력이 있는 아이템만 필터링 (거래 불가 아이템 제외)
    sold_data = await fetch_auction_sold(item_name)
    if sold_data:
        tradeable_ids = {row["itemId"] for row in sold_data}
        items = [item for item in items if item["itemId"] in tradeable_ids]
    if not items:
        await interaction.followup.send("경매장에서 거래 가능한 아이템이 없습니다.")
        return

    # 검색 결과를 이미지와 함께 embed로 보여주기
    embeds = await _build_item_embeds(items)

    if len(items) == 1:
        # 1개만 검색됨 - 확인용으로 이미지와 함께 바로 등록
        item = items[0]
        is_new = await add_watch_item(item["itemId"], item["itemName"], interaction.user.id)
        if is_new:
            count = await fetch_and_save_item_prices(item["itemId"], item["itemName"])
            embeds[0].set_footer(text=f"시세 추적 등록 완료 | 최초 수집: {count}건")
            await interaction.followup.send(
                content=f"'{item['itemName']}' 시세 추적을 시작합니다.",
                embed=embeds[0]
            )
        else:
            await interaction.followup.send(
                f"'{item['itemName']}'은(는) 이미 추적 중인 아이템입니다."
            )
        return

    # 여러 개 검색됨 - 이미지 embed + 선택 UI
    view = ItemSelectView(items, interaction.user.id)
    await interaction.followup.send(
        content=f"{len(items)}개의 아이템이 검색되었습니다. 아래에서 선택해주세요.",
        embeds=embeds,
        view=view,
        ephemeral=True
    )

    await view.wait()
    if view.selected_item:
        item = view.selected_item
        is_new = await add_watch_item(item["itemId"], item["itemName"], interaction.user.id)
        if is_new:
            count = await fetch_and_save_item_prices(item["itemId"], item["itemName"])
            await interaction.followup.send(
                f"'{item['itemName']}' 시세 추적 등록 완료 (최초 수집: {count}건)",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"'{item['itemName']}'은(는) 이미 추적 중인 아이템입니다.",
                ephemeral=True
            )


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


@app_commands.command(name="시세목록", description="현재 시세 추적 중인 아이템 목록을 조회합니다")
async def auction_watch_list(interaction: Interaction):
    logger.info(f"/시세목록 호출: 사용자={interaction.user.id}")

    items = await get_all_watch_items()
    if not items:
        await interaction.response.send_message("등록된 시세 추적 아이템이 없습니다.")
        return

    embeds = []
    for item in items[:10]:
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

    await interaction.response.send_message(
        content=f"시세 추적 중인 아이템 ({len(items)}개)",
        embeds=embeds
    )
