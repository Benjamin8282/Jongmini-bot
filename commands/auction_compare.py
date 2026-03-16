from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands, Interaction, ui

from core.db import get_price_history, get_watch_item_by_name, get_all_watch_items
from core.chart import aggregate_to_ohlc, generate_comparison_chart
from core.analysis import calc_correlation
from core.logger import logger
from commands.auction_chart import record_recent_item, _sort_by_recent

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


def _get_interval_label(interval_minutes: int) -> str:
    return next(
        (i["label"] for i in INTERVALS if i["minutes"] == interval_minutes),
        f"{interval_minutes}분봉"
    )


def _format_change_text(close: int, prev: int) -> str:
    """변동률 텍스트 포맷."""
    diff = close - prev
    pct = (diff / prev * 100) if prev else 0
    arrow = "▲" if diff > 0 else "▼" if diff < 0 else "−"
    return f"{close:,}G ({arrow} {abs(pct):.1f}%)"


def _calc_item_field(name: str, ohlc) -> tuple[str, str] | None:
    """아이템 현재가/변동률 필드 생성. (name, value) 또는 None."""
    if ohlc.empty:
        return None
    close = int(ohlc["close"].iloc[-1])
    val = _format_change_text(close, int(ohlc["close"].iloc[0])) if len(ohlc) >= 2 else f"{close:,}G"
    return name, val


def _build_main_embed(
    item_name_a: str, ohlc_a, item_name_b: str, ohlc_b,
    period_days: int, interval_label: str,
    records_a: list, records_b: list,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"{item_name_a} vs {item_name_b}",
        description=(
            f"기간: {period_days}일 | 간격: {interval_label}\n"
            f"거래 기록: {item_name_a} {len(records_a)}건 / "
            f"{item_name_b} {len(records_b)}건"
        ),
        color=0x9B59B6
    )
    for name, ohlc in [(item_name_a, ohlc_a), (item_name_b, ohlc_b)]:
        field = _calc_item_field(name, ohlc)
        if field:
            embed.add_field(name=field[0], value=field[1], inline=True)
    embed.set_image(url="attachment://compare_chart.png")
    return embed


def _corr_color(c: float) -> int:
    if c >= 0.3:
        return 0x2ED573
    if c <= -0.3:
        return 0xFF4757
    return 0x95A5A6


def _build_corr_embed_with_value(corr_result: dict) -> discord.Embed:
    c = corr_result["correlation"]
    interp = corr_result["interpretation"]
    overlap = corr_result["overlap_count"]
    trend_text = (
        '두 아이템의 가격이 함께 움직이는 경향이 있습니다.'
        if abs(c) >= 0.3
        else '두 아이템의 가격은 독립적으로 움직입니다.'
    )
    demand_text = '같은 컨텐츠 수요의 영향을 받을 수 있습니다.' if c >= 0.7 else ''
    embed = discord.Embed(
        title="상관관계 분석",
        description=(
            f"**피어슨 상관계수: {c:.3f}**\n"
            f"해석: {interp}\n"
            f"분석 대상: 겹치는 {overlap}개 캔들\n\n"
            f"{trend_text}\n{demand_text}"
        ),
        color=_corr_color(c)
    )
    embed.set_footer(
        text="상관관계는 인과관계를 의미하지 않습니다. 참고용으로만 활용하세요."
    )
    return embed


def _build_corr_embed_insufficient(corr_result: dict) -> discord.Embed:
    return discord.Embed(
        title="상관관계 분석",
        description=(
            f"겹치는 데이터가 부족하여 분석할 수 없습니다.\n"
            f"(최소 10캔들 필요, 현재 {corr_result['overlap_count']}캔들)\n\n"
            f"더 긴 기간이나 짧은 봉 간격을 선택해보세요."
        ),
        color=0x95A5A6
    )


def _build_corr_embed(corr_result: dict | None) -> discord.Embed | None:
    if not corr_result:
        return None
    if corr_result["correlation"] is not None:
        return _build_corr_embed_with_value(corr_result)
    return _build_corr_embed_insufficient(corr_result)


def _fetch_time_range(period_days: int) -> tuple[str, str]:
    end_dt = datetime.now(KST)
    start_dt = end_dt - timedelta(days=period_days)
    return start_dt.strftime("%Y-%m-%d %H:%M:%S"), end_dt.strftime("%Y-%m-%d %H:%M:%S")


def _check_records(records_a, records_b, item_name_a, item_name_b, period_days):
    """거래 기록 유효성 체크. 에러 str 또는 None."""
    if not records_a and not records_b:
        return f"두 아이템 모두 해당 기간({period_days}일) 거래 기록이 없습니다."
    if not records_a:
        return f"'{item_name_a}'의 해당 기간({period_days}일) 거래 기록이 없습니다."
    if not records_b:
        return f"'{item_name_b}'의 해당 기간({period_days}일) 거래 기록이 없습니다."
    return None


def _calc_corr_result(ohlc_a, ohlc_b) -> dict | None:
    """두 OHLC 시리즈 간 상관관계 계산. 둘 중 하나라도 비어있으면 None."""
    if ohlc_a.empty or ohlc_b.empty:
        return None
    return calc_correlation(ohlc_a["close"], ohlc_b["close"])


async def _fetch_pair_records(item_id_a, item_id_b, period_days):
    """두 아이템의 가격 이력을 조회."""
    start_str, end_str = _fetch_time_range(period_days)
    records_a = await get_price_history(item_id_a, start_str, end_str)
    records_b = await get_price_history(item_id_b, start_str, end_str)
    return records_a, records_b


def _both_ohlc_empty(ohlc_a, ohlc_b):
    return ohlc_a.empty and ohlc_b.empty


async def _build_comparison(
    item_id_a: str, item_name_a: str,
    item_id_b: str, item_name_b: str,
    interval_minutes: int, period_days: int,
):
    """비교 차트 생성. (embeds, file) 또는 에러 str 반환."""
    records_a, records_b = await _fetch_pair_records(item_id_a, item_id_b, period_days)

    err = _check_records(records_a, records_b, item_name_a, item_name_b, period_days)
    if err:
        return err

    interval_label = _get_interval_label(interval_minutes)
    ohlc_a = aggregate_to_ohlc(records_a, interval_minutes)
    ohlc_b = aggregate_to_ohlc(records_b, interval_minutes)

    if _both_ohlc_empty(ohlc_a, ohlc_b):
        return "OHLC 데이터를 생성할 수 없습니다."

    corr_result = _calc_corr_result(ohlc_a, ohlc_b)
    corr_val = corr_result["correlation"] if corr_result else None
    chart_buf = generate_comparison_chart(
        item_name_a, ohlc_a, item_name_b, ohlc_b,
        interval_label, corr_val
    )
    if not chart_buf:
        return "차트 생성에 실패했습니다."

    file = discord.File(chart_buf, filename="compare_chart.png")
    embed = _build_main_embed(
        item_name_a, ohlc_a, item_name_b, ohlc_b,
        period_days, interval_label, records_a, records_b,
    )
    corr_embed = _build_corr_embed(corr_result)
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


def _exclude_item(items: list[dict], exclude: str | None) -> list[dict]:
    """제외할 아이템을 필터링."""
    return [i for i in items if i["item_name"] != exclude] if exclude else items


def _filter_items(items: list[dict], current: str, exclude: str = None,
                  user_id: int = 0) -> list[dict]:
    items = _exclude_item(items, exclude)
    sorted_items = _sort_by_recent(items, user_id)
    if not current:
        return sorted_items[:25]
    current_lower = current.lower()
    return [i for i in sorted_items if current_lower in i["item_name"].lower()][:25]


async def _autocomplete_items(
    interaction: Interaction, current: str, exclude: str = None
) -> list[app_commands.Choice[str]]:
    items = await get_all_watch_items()
    filtered = _filter_items(items, current, exclude, interaction.user.id)
    return [
        app_commands.Choice(name=item["item_name"], value=item["item_name"])
        for item in filtered
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


async def _validate_compare_items(
    interaction: Interaction, item_name_a: str, item_name_b: str
) -> tuple[dict, dict] | None:
    """비교 대상 아이템 유효성 검사. 실패 시 None (응답 전송 포함)."""
    if item_name_a == item_name_b:
        await interaction.followup.send("같은 아이템은 비교할 수 없습니다.")
        return None
    watch_a = await get_watch_item_by_name(item_name_a)
    watch_b = await get_watch_item_by_name(item_name_b)
    unregistered = item_name_a if not watch_a else (item_name_b if not watch_b else None)
    if unregistered:
        await interaction.followup.send(
            f"'{unregistered}'은(는) 등록되지 않은 아이템입니다. "
            f"`/시세등록`으로 먼저 등록해주세요."
        )
        return None
    return watch_a, watch_b


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

    validated = await _validate_compare_items(interaction, item_name_a, item_name_b)
    if not validated:
        return
    watch_a, watch_b = validated
    record_recent_item(interaction.user.id, watch_a["item_name"])
    record_recent_item(interaction.user.id, watch_b["item_name"])

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
        embeds = [embed] + ([corr_embed] if corr_embed else [])
        msg = await interaction.followup.send(embeds=embeds, file=file, view=view)
    view.message = msg
