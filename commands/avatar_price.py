import discord
from discord import app_commands, Interaction
from statistics import median

from commands.avatar_search import JOB_CHOICES, RARITY_CHOICES, SLOT_CHOICES
from commands.total import PaginationView
from core.avatar_market_api import fetch_avatar_sold
from core.logger import logger

# 선물/양도 거래 필터 기준 (10골드 이하)
_MIN_PRICE_THRESHOLD = 10


def _filter_valid_prices(goods_list: list[dict]) -> list[dict]:
    """선물/양도 거래(가격 <= 10) 필터링."""
    return [g for g in goods_list if g.get("price", 0) > _MIN_PRICE_THRESHOLD]


def _calc_stats(prices: list[int]) -> dict:
    """가격 리스트에서 통계 계산."""
    return {
        "avg": sum(prices) // len(prices),
        "min": min(prices),
        "max": max(prices),
        "median": int(median(prices)),
        "count": len(prices),
    }


def _build_summary_embed(stats: dict, rarity: str | None) -> discord.Embed:
    """시세 요약 Embed 생성."""
    title = "아바타 마켓 시세 요약"
    if rarity:
        title += f" ({rarity})"

    embed = discord.Embed(title=title, color=0x2ECC71)
    embed.add_field(name="평균가", value=f"{stats['avg']:,}G", inline=True)
    embed.add_field(name="최저가", value=f"{stats['min']:,}G", inline=True)
    embed.add_field(name="최고가", value=f"{stats['max']:,}G", inline=True)
    embed.add_field(name="중간가", value=f"{stats['median']:,}G", inline=True)
    embed.add_field(name="거래건수", value=f"{stats['count']}건", inline=True)
    return embed


def _format_job_names(jobs: list[dict]) -> str:
    """직업 목록을 문자열로 포맷."""
    if not jobs:
        return "전체"
    return ", ".join(j.get("jobName", "?") for j in jobs)


def _build_trade_line(goods: dict) -> str:
    """거래 내역 1건을 문자열로 포맷."""
    title = goods.get("title", "제목 없음")
    price = goods.get("price", 0)
    sold_date = goods.get("soldDate", "알 수 없음")
    job_str = _format_job_names(goods.get("jobs", []))
    return f"**{title}** - {price:,}G\n{job_str} | {sold_date}"


def _build_trades_embeds(recent: list[dict]) -> list[discord.Embed]:
    """최근 거래 내역 Embed 리스트 생성 (15건씩 분할)."""
    embeds = []
    for i in range(0, len(recent), 15):
        chunk = recent[i:i + 15]
        lines = [_build_trade_line(g) for g in chunk]
        desc = "\n\n".join(lines)
        page_num = (i // 15) + 1
        embed = discord.Embed(
            title=f"최근 거래 내역 ({page_num})",
            description=desc,
            color=0x3498DB,
        )
        embeds.append(embed)
    return embeds


async def _send_results(
    interaction: Interaction,
    summary: discord.Embed,
    trade_embeds: list[discord.Embed],
):
    """요약 + 거래내역을 전송. 5개 초과 시 PaginationView 사용."""
    all_embeds = [summary] + trade_embeds
    if len(all_embeds) <= 5:
        await interaction.followup.send(embeds=all_embeds)
        return
    pages = [all_embeds[i:i + 5] for i in range(0, len(all_embeds), 5)]
    view = PaginationView(pages, user_id=interaction.user.id)
    await interaction.followup.send(embeds=pages[0], view=view)


@app_commands.command(
    name="아바타시세",
    description="아바타 마켓 최근 거래 시세를 조회합니다",
)
@app_commands.describe(
    직업="검색할 직업 (선택)",
    레어리티="아바타 등급 (선택)",
    부위="아바타 부위 (선택)",
)
@app_commands.choices(직업=JOB_CHOICES, 레어리티=RARITY_CHOICES, 부위=SLOT_CHOICES)
async def avatar_price(
    interaction: Interaction,
    직업: app_commands.Choice[str] = None,
    레어리티: app_commands.Choice[str] = None,
    부위: app_commands.Choice[str] = None,
):
    logger.info(
        f"/아바타시세 호출: 사용자={interaction.user.id}, "
        f"직업={직업}, 레어리티={레어리티}, 부위={부위}"
    )
    # noinspection PyUnresolvedReferences
    await interaction.response.defer(thinking=True)

    job_id = 직업.value if 직업 else None
    rarity_val = 레어리티.value if 레어리티 else None
    slot_id = 부위.value if 부위 else None
    goods_list = await fetch_avatar_sold(
        job_id=job_id,
        avatar_rarity=rarity_val,
        slot_id=slot_id,
    )

    if not goods_list:
        await interaction.followup.send("거래 내역이 없습니다.", ephemeral=True)
        return

    # 선물/양도 거래 필터링
    filtered = _filter_valid_prices(goods_list)
    if not filtered:
        await interaction.followup.send(
            "유효한 거래 내역이 없습니다 (선물/양도 제외).",
            ephemeral=True,
        )
        return

    prices = [g.get("price", 0) for g in filtered]
    stats = _calc_stats(prices)
    summary = _build_summary_embed(stats, rarity_val)

    # 최근 15건 거래 내역
    recent = filtered[:15]
    trade_embeds = _build_trades_embeds(recent)

    await _send_results(interaction, summary, trade_embeds)
    logger.info(f"/아바타시세 결과 전송: 사용자={interaction.user.id}, 거래 {stats['count']}건")
