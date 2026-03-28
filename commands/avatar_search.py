import discord
from discord import app_commands, Interaction

from commands.total import PaginationView
from core.avatar_market_api import (
    fetch_avatar_sale, fetch_avatar_hashtags,
)
from core.logger import logger

# 레어리티별 Embed 색상
_RARITY_COLORS = {
    "레어": 0xFFB400,
    "클론": 0x9B59B6,
    "상급": 0x3498DB,
}
_DEFAULT_COLOR = 0x95A5A6

# 직업 Choice (DNF 17개 직업 고정)
JOB_CHOICES = [
    app_commands.Choice(name="귀검사(남)", value="41f1cdc2ff58bb5fdc287be0db2a8df3"),
    app_commands.Choice(name="격투가(여)", value="a7a059ebe9e6054c0644b40ef316d6e9"),
    app_commands.Choice(name="거너(남)", value="afdf3b989339de478e85b614d274d1ef"),
    app_commands.Choice(name="마법사(여)", value="3909d0b188e9c95311399f776e331da5"),
    app_commands.Choice(name="프리스트(남)", value="f6a4ad30555b99b499c07835f87ce522"),
    app_commands.Choice(name="거너(여)", value="944b9aab492c15a8474f96947ceeb9e4"),
    app_commands.Choice(name="도적", value="ddc49e9ad1ff72a00b53c6cff5b1e920"),
    app_commands.Choice(name="격투가(남)", value="ca0f0e0e9e1d55b5f9955b03d9dd213c"),
    app_commands.Choice(name="마법사(남)", value="a5ccbaf5538981c6ef99b236c0a60b73"),
    app_commands.Choice(name="다크나이트", value="17e417b31686389eebff6d754c3401ea"),
    app_commands.Choice(name="크리에이터", value="b522a95d819a5559b775deb9a490e49a"),
    app_commands.Choice(name="귀검사(여)", value="1645c45aabb008c98406b3a16447040d"),
    app_commands.Choice(name="나이트", value="0ee8fa5dc525c1a1f23fc6911e921e4a"),
    app_commands.Choice(name="총검사", value="3deb7be5f01953ac8b1ecaa1e25e0420"),
    app_commands.Choice(name="프리스트(여)", value="0c1b401bb09241570d364420b3ba3fd7"),
    app_commands.Choice(name="외전검사", value="986c2b3d72ee0e4a0b7fcfbe786d4e02"),
    app_commands.Choice(name="아처", value="b9cb48777665de22c006fabaf9a560b3"),
]

RARITY_CHOICES = [
    app_commands.Choice(name="커먼", value="커먼"),
    app_commands.Choice(name="언커먼", value="언커먼"),
    app_commands.Choice(name="레어", value="레어"),
    app_commands.Choice(name="클론", value="클론"),
    app_commands.Choice(name="상급", value="상급"),
]

SLOT_CHOICES = [
    app_commands.Choice(name="모자", value="HEADGEAR"),
    app_commands.Choice(name="머리", value="HAIR"),
    app_commands.Choice(name="얼굴", value="FACE"),
    app_commands.Choice(name="상의", value="JACKET"),
    app_commands.Choice(name="하의", value="PANTS"),
    app_commands.Choice(name="신발", value="SHOES"),
    app_commands.Choice(name="목가슴", value="BREAST"),
    app_commands.Choice(name="허리", value="WAIST"),
    app_commands.Choice(name="스킨", value="SKIN"),
    app_commands.Choice(name="오라", value="AURORA"),
    app_commands.Choice(name="무기", value="WEAPON"),
    app_commands.Choice(name="오라 스킨", value="AURA_SKIN"),
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
    부위="아바타 부위 (선택)",
    해시태그="해시태그 필터 (선택)",
)
@app_commands.choices(직업=JOB_CHOICES, 레어리티=RARITY_CHOICES, 부위=SLOT_CHOICES)
@app_commands.autocomplete(해시태그=hashtag_autocomplete)
async def avatar_search(
    interaction: Interaction,
    직업: app_commands.Choice[str] = None,
    레어리티: app_commands.Choice[str] = None,
    부위: app_commands.Choice[str] = None,
    해시태그: str = None,
):
    logger.info(
        f"/아바타검색 호출: 사용자={interaction.user.id}, "
        f"직업={직업}, 레어리티={레어리티}, 부위={부위}, 해시태그={해시태그}"
    )
    # noinspection PyUnresolvedReferences
    await interaction.response.defer(thinking=True)

    job_id = 직업.value if 직업 else None
    rarity_val = 레어리티.value if 레어리티 else None
    slot_id = 부위.value if 부위 else None
    goods_list = await fetch_avatar_sale(
        job_id=job_id,
        avatar_rarity=rarity_val,
        slot_id=slot_id,
        hashtag=해시태그,
    )

    if not goods_list:
        await interaction.followup.send("검색 결과가 없습니다.", ephemeral=True)
        return

    embeds = _build_all_embeds(goods_list)
    await _send_results(interaction, embeds)
    logger.info(f"/아바타검색 결과 {len(embeds)}건 전송: 사용자={interaction.user.id}")
