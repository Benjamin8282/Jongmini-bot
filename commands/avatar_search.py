import discord
from discord import app_commands, Interaction

from commands.total import PaginationView
from core.avatar_market_api import (
    fetch_avatar_sale, fetch_jobs, fetch_avatar_hashtags,
)
from core.logger import logger

# 레어리티별 Embed 색상
_RARITY_COLORS = {
    "레어": 0xFFB400,
    "클론": 0x9B59B6,
    "상급": 0x3498DB,
}
_DEFAULT_COLOR = 0x95A5A6


def _filter_jobs(jobs: list[dict], current: str) -> list[dict]:
    if not current:
        return jobs[:25]
    lower = current.lower()
    return [j for j in jobs if lower in j["jobName"].lower()][:25]


async def job_autocomplete(
    interaction: Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """직업 캐시에서 자동완성 제공."""
    jobs = await fetch_jobs()
    return [
        app_commands.Choice(name=j["jobName"], value=j["jobId"])
        for j in _filter_jobs(jobs, current)
    ]


def _filter_tags(tags: list[str], current: str) -> list[str]:
    if not current:
        return tags[:25]
    lower = current.lower()
    return [t for t in tags if lower in t.lower()][:25]


async def hashtag_autocomplete(
    interaction: Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """해시태그 캐시에서 자동완성 제공."""
    tags = await fetch_avatar_hashtags()
    return [app_commands.Choice(name=t, value=t) for t in _filter_tags(tags, current)]


def _get_embed_color(rarity: str | None) -> int:
    """레어리티에 따른 Embed 색상 반환."""
    if rarity is None:
        return _DEFAULT_COLOR
    return _RARITY_COLORS.get(rarity, _DEFAULT_COLOR)


def _format_slots(avatars: list[dict]) -> str:
    """아바타 슬롯 이름을 컴팩트 리스트로 포맷."""
    if not avatars:
        return "없음"
    return ", ".join(a.get("slotName", "?") for a in avatars)


def _format_emblem(emblem: dict | None) -> str:
    """엠블렘 정보 포맷."""
    if not emblem or emblem.get("code") == 100:
        return "없음"
    return emblem.get("name", "없음")


def _format_jobs(jobs: list[dict]) -> str:
    """직업 목록을 문자열로 포맷."""
    if not jobs:
        return "전체"
    return ", ".join(j.get("jobName", "?") for j in jobs)


def _build_goods_embed(goods: dict) -> discord.Embed:
    """상품 1개를 Embed로 변환."""
    rarity = goods.get("avatarRarity")
    color = _get_embed_color(rarity)
    title = goods.get("title", "제목 없음")
    price = goods.get("price", 0)

    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="가격", value=f"{price:,}G", inline=True)
    embed.add_field(name="직업", value=_format_jobs(goods.get("jobs", [])), inline=True)
    embed.add_field(name="등급", value=rarity or "미분류", inline=True)
    embed.add_field(
        name="부위",
        value=_format_slots(goods.get("avatar", [])),
        inline=False,
    )
    embed.add_field(
        name="엠블렘",
        value=_format_emblem(goods.get("emblem")),
        inline=True,
    )
    return embed


def _build_all_embeds(goods_list: list[dict]) -> list[discord.Embed]:
    """상품 리스트를 Embed 리스트로 변환."""
    return [_build_goods_embed(g) for g in goods_list]


async def _send_results(interaction: Interaction, embeds: list[discord.Embed]):
    """결과 Embed를 전송. 5개 초과 시 PaginationView 사용."""
    if len(embeds) <= 5:
        await interaction.followup.send(embeds=embeds)
        return
    pages = [embeds[i:i + 5] for i in range(0, len(embeds), 5)]
    view = PaginationView(pages, user_id=interaction.user.id)
    await interaction.followup.send(embeds=pages[0], view=view)


@app_commands.command(
    name="아바타검색",
    description="아바타 마켓에서 판매 중인 아바타를 검색합니다",
)
@app_commands.describe(
    직업="검색할 직업 (선택)",
    레어리티="아바타 등급 (선택)",
    해시태그="해시태그 필터 (선택)",
)
@app_commands.choices(레어리티=[
    app_commands.Choice(name="커먼", value="커먼"),
    app_commands.Choice(name="언커먼", value="언커먼"),
    app_commands.Choice(name="레어", value="레어"),
    app_commands.Choice(name="클론", value="클론"),
    app_commands.Choice(name="상급", value="상급"),
])
@app_commands.autocomplete(직업=job_autocomplete, 해시태그=hashtag_autocomplete)
async def avatar_search(
    interaction: Interaction,
    직업: str = None,
    레어리티: app_commands.Choice[str] = None,
    해시태그: str = None,
):
    logger.info(
        f"/아바타검색 호출: 사용자={interaction.user.id}, "
        f"직업={직업}, 레어리티={레어리티}, 해시태그={해시태그}"
    )
    # noinspection PyUnresolvedReferences
    await interaction.response.defer(thinking=True)

    rarity_val = 레어리티.value if 레어리티 else None
    goods_list = await fetch_avatar_sale(
        job_id=직업,
        avatar_rarity=rarity_val,
        hashtag=해시태그,
    )

    if not goods_list:
        await interaction.followup.send("검색 결과가 없습니다.", ephemeral=True)
        return

    embeds = _build_all_embeds(goods_list)
    await _send_results(interaction, embeds)
    logger.info(f"/아바타검색 결과 {len(embeds)}건 전송: 사용자={interaction.user.id}")
