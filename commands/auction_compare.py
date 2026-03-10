from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands, Interaction, ui

from core.db import get_price_history, get_watch_item_by_name, get_all_watch_items
from core.chart import aggregate_to_ohlc, generate_comparison_chart
from core.analysis import calc_correlation
from core.logger import logger

KST = timezone(timedelta(hours=9))

ITEM_IMAGE_URL = "https://img-api.neople.co.kr/df/items/{item_id}"

INTERVALS = [
    {"label": "1분봉", "minutes": 1},
    {"label": "15분봉", "minutes": 15},
    {"label": "1시간봉", "minutes": 60},
    {"label": "4시간봉", "minutes": 240},
    {"label": "1일봉", "minutes": 1440},
]

PERIODS = [
    {"label": "1일", "days": 1},
    {"label": "3일", "days": 3},
    {"label": "7일", "days": 7},
    {"label": "30일", "days": 30},
]

_user_prefs: dict[int, dict[str, int]] = {}


def _save_user_pref(user_id: int, interval: int = None, period: int = None):
    pref = _user_prefs.setdefault(user_id, {"interval": 60, "period": 7})
    if interval is not None:
        pref["interval"] = interval
    if period is not None:
        pref["period"] = period


async def _build_comparison(
    item_id_a: str, item_name_a: str,
    item_id_b: str, item_name_b: str,
    interval_minutes: int, period_days: int,
):
    """비교 차트 생성. (embeds, file) 또는 에러 str 반환."""
    end_dt = datetime.now(KST)
    start_dt = end_dt - timedelta(days=period_days)
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")

    records_a = await get_price_history(item_id_a, start_str, end_str)
    records_b = await get_price_history(item_id_b, start_str, end_str)

    if not records_a and not records_b:
        return f"두 아이템 모두 해당 기간({period_days}일) 거래 기록이 없습니다."
    if not records_a:
        return f"'{item_name_a}'의 해당 기간({period_days}일) 거래 기록이 없습니다."
    if not records_b:
        return f"'{item_name_b}'의 해당 기간({period_days}일) 거래 기록이 없습니다."

    interval_label = next(
        (i["label"] for i in INTERVALS if i["minutes"] == interval_minutes),
        f"{interval_minutes}분봉"
    )

    ohlc_a = aggregate_to_ohlc(records_a, interval_minutes)
    ohlc_b = aggregate_to_ohlc(records_b, interval_minutes)

    if ohlc_a.empty and ohlc_b.empty:
        return "OHLC 데이터를 생성할 수 없습니다."

    # 상관관계 분석
    corr_result = None
    if not ohlc_a.empty and not ohlc_b.empty:
        corr_result = calc_correlation(ohlc_a["close"], ohlc_b["close"])

    corr_val = corr_result["correlation"] if corr_result else None

    chart_buf = generate_comparison_chart(
        item_name_a, ohlc_a, item_name_b, ohlc_b,
        interval_label, corr_val
    )
    if not chart_buf:
        return "차트 생성에 실패했습니다."

    file = discord.File(chart_buf, filename="compare_chart.png")

    # 메인 embed
    embed = discord.Embed(
        title=f"{item_name_a} vs {item_name_b}",
        description=(
            f"기간: {period_days}일 | 간격: {interval_label}\n"
            f"거래 기록: {item_name_a} {len(records_a)}건 / "
            f"{item_name_b} {len(records_b)}건"
        ),
        color=0x9B59B6
    )

    # 각 아이템 현재가/변동률
    for name, ohlc in [(item_name_a, ohlc_a), (item_name_b, ohlc_b)]:
        if ohlc.empty or len(ohlc) < 1:
            continue
        close = int(ohlc["close"].iloc[-1])
        if len(ohlc) >= 2:
            prev = int(ohlc["close"].iloc[0])
            diff = close - prev
            pct = (diff / prev * 100) if prev else 0
            arrow = "▲" if diff > 0 else "▼" if diff < 0 else "−"
            val = f"{close:,}G ({arrow} {abs(pct):.1f}%)"
        else:
            val = f"{close:,}G"
        embed.add_field(name=name, value=val, inline=True)

    embed.set_image(url="attachment://compare_chart.png")

    # 상관관계 embed
    corr_embed = None
    if corr_result:
        if corr_result["correlation"] is not None:
            c = corr_result["correlation"]
            interp = corr_result["interpretation"]
            overlap = corr_result["overlap_count"]

            if c >= 0.3:
                corr_color = 0x2ED573
            elif c <= -0.3:
                corr_color = 0xFF4757
            else:
                corr_color = 0x95A5A6

            corr_embed = discord.Embed(
                title="상관관계 분석",
                description=(
                    f"**피어슨 상관계수: {c:.3f}**\n"
                    f"해석: {interp}\n"
                    f"분석 대상: 겹치는 {overlap}개 캔들\n\n"
                    f"{'두 아이템의 가격이 함께 움직이는 경향이 있습니다.' if abs(c) >= 0.3 else '두 아이템의 가격은 독립적으로 움직입니다.'}\n"
                    f"{'같은 컨텐츠 수요의 영향을 받을 수 있습니다.' if c >= 0.7 else ''}"
                ),
                color=corr_color
            )
            corr_embed.set_footer(
                text="상관관계는 인과관계를 의미하지 않습니다. 참고용으로만 활용하세요."
            )
        else:
            corr_embed = discord.Embed(
                title="상관관계 분석",
                description=(
                    f"겹치는 데이터가 부족하여 분석할 수 없습니다.\n"
                    f"(최소 10캔들 필요, 현재 {corr_result['overlap_count']}캔들)\n\n"
                    f"더 긴 기간이나 짧은 봉 간격을 선택해보세요."
                ),
                color=0x95A5A6
            )

    return embed, file, corr_embed


class CompareControlView(ui.View):
    """비교 차트 간격/기간 버튼 View"""
    def __init__(self, item_id_a: str, item_name_a: str,
                 item_id_b: str, item_name_b: str,
                 interval_minutes: int = 60, period_days: int = 7):
        super().__init__(timeout=300)
        self.item_id_a = item_id_a
        self.item_name_a = item_name_a
        self.item_id_b = item_id_b
        self.item_name_b = item_name_b
        self.interval_minutes = interval_minutes
        self.period_days = period_days
        self.message = None
        self._update_buttons()

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.delete()
            except Exception:
                pass

    def _update_buttons(self):
        self.clear_items()

        for iv in INTERVALS:
            active = iv["minutes"] == self.interval_minutes
            btn = ui.Button(
                label=iv["label"],
                style=discord.ButtonStyle.primary if active else discord.ButtonStyle.secondary,
                custom_id=f"cmp_iv_{iv['minutes']}",
                row=0
            )
            btn.callback = self._make_interval_callback(iv["minutes"])
            self.add_item(btn)

        for pd_item in PERIODS:
            active = pd_item["days"] == self.period_days
            btn = ui.Button(
                label=pd_item["label"],
                style=discord.ButtonStyle.success if active else discord.ButtonStyle.secondary,
                custom_id=f"cmp_pd_{pd_item['days']}",
                row=1
            )
            btn.callback = self._make_period_callback(pd_item["days"])
            self.add_item(btn)

    def _make_interval_callback(self, minutes: int):
        async def callback(interaction: Interaction):
            self.interval_minutes = minutes
            _save_user_pref(interaction.user.id, interval=minutes)
            await self._refresh(interaction)
        return callback

    def _make_period_callback(self, days: int):
        async def callback(interaction: Interaction):
            self.period_days = days
            _save_user_pref(interaction.user.id, period=days)
            await self._refresh(interaction)
        return callback

    async def _refresh(self, interaction: Interaction):
        await interaction.response.defer()
        self._update_buttons()

        result = await _build_comparison(
            self.item_id_a, self.item_name_a,
            self.item_id_b, self.item_name_b,
            self.interval_minutes, self.period_days
        )

        if isinstance(result, str):
            await interaction.edit_original_response(
                content=result, embeds=[], attachments=[], view=self
            )
        else:
            embed, file, corr_embed = result
            embeds = [embed]
            if corr_embed:
                embeds.append(corr_embed)
            await interaction.edit_original_response(
                content=None, embeds=embeds, attachments=[file], view=self
            )


async def _autocomplete_items(
    interaction: Interaction, current: str, exclude: str = None
) -> list[app_commands.Choice[str]]:
    items = await get_all_watch_items()
    if exclude:
        items = [i for i in items if i["item_name"] != exclude]
    if not current:
        return [
            app_commands.Choice(name=item["item_name"], value=item["item_name"])
            for item in items[:25]
        ]
    current_lower = current.lower()
    matches = [
        item for item in items
        if current_lower in item["item_name"].lower()
    ]
    return [
        app_commands.Choice(name=item["item_name"], value=item["item_name"])
        for item in matches[:25]
    ]


async def autocomplete_a(
    interaction: Interaction, current: str
) -> list[app_commands.Choice[str]]:
    return await _autocomplete_items(interaction, current)


async def autocomplete_b(
    interaction: Interaction, current: str
) -> list[app_commands.Choice[str]]:
    exclude = getattr(interaction.namespace, "item_name_a", None)
    return await _autocomplete_items(interaction, current, exclude=exclude)


@app_commands.command(
    name="시세비교",
    description="두 아이템의 경매장 시세를 비교 분석합니다"
)
@app_commands.describe(
    item_name_a="첫 번째 아이템 (등록된 아이템에서 자동완성)",
    item_name_b="두 번째 아이템 (등록된 아이템에서 자동완성)",
)
@app_commands.autocomplete(item_name_a=autocomplete_a, item_name_b=autocomplete_b)
async def auction_compare(interaction: Interaction, item_name_a: str, item_name_b: str):
    logger.info(
        f"/시세비교 호출: 사용자={interaction.user.id}, "
        f"A={item_name_a}, B={item_name_b}"
    )
    await interaction.response.defer(thinking=True)

    if item_name_a == item_name_b:
        await interaction.followup.send("같은 아이템은 비교할 수 없습니다.")
        return

    watch_a = await get_watch_item_by_name(item_name_a)
    watch_b = await get_watch_item_by_name(item_name_b)

    if not watch_a:
        await interaction.followup.send(
            f"'{item_name_a}'은(는) 등록되지 않은 아이템입니다. "
            f"`/시세등록`으로 먼저 등록해주세요."
        )
        return
    if not watch_b:
        await interaction.followup.send(
            f"'{item_name_b}'은(는) 등록되지 않은 아이템입니다. "
            f"`/시세등록`으로 먼저 등록해주세요."
        )
        return

    pref = _user_prefs.get(interaction.user.id, {})
    interval = pref.get("interval", 60)
    period = pref.get("period", 7)

    view = CompareControlView(
        watch_a["item_id"], watch_a["item_name"],
        watch_b["item_id"], watch_b["item_name"],
        interval_minutes=interval, period_days=period
    )

    result = await _build_comparison(
        watch_a["item_id"], watch_a["item_name"],
        watch_b["item_id"], watch_b["item_name"],
        interval_minutes=interval, period_days=period
    )

    if isinstance(result, str):
        msg = await interaction.followup.send(content=result, view=view)
    else:
        embed, file, corr_embed = result
        embeds = [embed]
        if corr_embed:
            embeds.append(corr_embed)
        msg = await interaction.followup.send(embeds=embeds, file=file, view=view)
    view.message = msg
