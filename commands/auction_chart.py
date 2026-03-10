from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands, Interaction, ui

from core.db import get_price_history, get_watch_item_by_name, get_all_watch_items
from core.chart import aggregate_to_ohlc, generate_candlestick_chart
from core.analysis import analyze, format_analysis_text
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

# 사용자별 마지막 설정 저장 {user_id: {"interval": int, "period": int}}
_user_prefs: dict[int, dict[str, int]] = {}


def _save_user_pref(user_id: int, interval: int = None, period: int = None):
    pref = _user_prefs.setdefault(user_id, {"interval": 60, "period": 7})
    if interval is not None:
        pref["interval"] = interval
    if period is not None:
        pref["period"] = period


async def _build_chart(item_id: str, item_name: str, interval_minutes: int, period_days: int):
    """차트 생성 후 (embed, file) 또는 에러 메시지 str 반환"""
    end_dt = datetime.now(KST)
    start_dt = end_dt - timedelta(days=period_days)
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")

    records = await get_price_history(item_id, start_str, end_str)
    if not records:
        return f"해당 기간({period_days}일) 거래 기록이 없습니다."

    interval_label = next(
        (i["label"] for i in INTERVALS if i["minutes"] == interval_minutes),
        f"{interval_minutes}분봉"
    )

    ohlc_df = aggregate_to_ohlc(records, interval_minutes)
    if ohlc_df.empty:
        return "OHLC 데이터를 생성할 수 없습니다."

    chart_buf = generate_candlestick_chart(item_name, ohlc_df, interval_label)
    if not chart_buf:
        return "차트 생성에 실패했습니다."

    # 최근 캔들 OHLCV 정보
    latest = ohlc_df.iloc[-1]
    prev = ohlc_df.iloc[-2] if len(ohlc_df) >= 2 else None

    close_price = int(latest["close"])
    change_text = ""
    if prev is not None:
        prev_close = int(prev["close"])
        diff = close_price - prev_close
        pct = (diff / prev_close * 100) if prev_close else 0
        arrow = "▲" if diff > 0 else "▼" if diff < 0 else "−"
        change_text = f"{arrow} {abs(diff):,} ({abs(pct):.1f}%)"

    file = discord.File(chart_buf, filename="auction_chart.png")
    embed = discord.Embed(
        title=f"{item_name} 시세 차트",
        description=(
            f"기간: {period_days}일 | 간격: {interval_label}\n"
            f"거래 기록: {len(records)}건 | 캔들: {len(ohlc_df)}개"
        ),
        color=0xE74C3C if (prev is not None and close_price > int(prev["close"]))
        else 0x3498DB if (prev is not None and close_price < int(prev["close"]))
        else 0x2ECC71
    )
    embed.add_field(name="시가", value=f"{int(latest['open']):,}", inline=True)
    embed.add_field(name="고가", value=f"{int(latest['high']):,}", inline=True)
    embed.add_field(name="저가", value=f"{int(latest['low']):,}", inline=True)
    embed.add_field(name="종가", value=f"{close_price:,}", inline=True)
    embed.add_field(name="거래량", value=f"{int(latest['volume']):,}", inline=True)
    if change_text:
        embed.add_field(name="전봉대비", value=change_text, inline=True)
    embed.set_image(url="attachment://auction_chart.png")
    embed.set_thumbnail(url=ITEM_IMAGE_URL.format(item_id=item_id))

    # 분석 의견 embed
    analysis_embed = None
    if len(ohlc_df) >= 5:
        result = analyze(ohlc_df)
        analysis_text = format_analysis_text(result)

        score = result["score"]
        analysis_color = (
            0xE74C3C if score >= 1
            else 0x3498DB if score <= -1
            else 0x95A5A6
        )
        analysis_embed = discord.Embed(
            title="분석 의견",
            description=analysis_text,
            color=analysis_color
        )
        analysis_embed.set_footer(
            text="이 분석은 기술적 지표 기반 참고용이며, 투자 조언이 아닙니다."
        )

    return embed, file, analysis_embed


class ChartControlView(ui.View):
    """차트 간격/기간을 버튼으로 조작하는 View"""
    def __init__(self, item_id: str, item_name: str,
                 interval_minutes: int = 60, period_days: int = 7):
        super().__init__(timeout=300)
        self.item_id = item_id
        self.item_name = item_name
        self.interval_minutes = interval_minutes
        self.period_days = period_days
        self.message = None  # 타임아웃 시 삭제용
        self._update_buttons()

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.delete()
            except Exception:
                pass

    def _update_buttons(self):
        self.clear_items()

        # 간격 버튼 행
        for iv in INTERVALS:
            active = iv["minutes"] == self.interval_minutes
            btn = ui.Button(
                label=iv["label"],
                style=discord.ButtonStyle.primary if active else discord.ButtonStyle.secondary,
                custom_id=f"interval_{iv['minutes']}",
                row=0
            )
            btn.callback = self._make_interval_callback(iv["minutes"])
            self.add_item(btn)

        # 기간 버튼 행
        for pd in PERIODS:
            active = pd["days"] == self.period_days
            btn = ui.Button(
                label=pd["label"],
                style=discord.ButtonStyle.success if active else discord.ButtonStyle.secondary,
                custom_id=f"period_{pd['days']}",
                row=1
            )
            btn.callback = self._make_period_callback(pd["days"])
            self.add_item(btn)

    def _make_interval_callback(self, minutes: int):
        async def callback(interaction: Interaction):
            self.interval_minutes = minutes
            _save_user_pref(interaction.user.id, interval=minutes)
            await self._refresh_chart(interaction)
        return callback

    def _make_period_callback(self, days: int):
        async def callback(interaction: Interaction):
            self.period_days = days
            _save_user_pref(interaction.user.id, period=days)
            await self._refresh_chart(interaction)
        return callback

    async def _refresh_chart(self, interaction: Interaction):
        await interaction.response.defer()
        self._update_buttons()

        result = await _build_chart(
            self.item_id, self.item_name,
            self.interval_minutes, self.period_days
        )

        if isinstance(result, str):
            await interaction.edit_original_response(
                content=result, embed=None, attachments=[], view=self
            )
        else:
            embed, file, analysis_embed = result
            embeds = [embed]
            if analysis_embed:
                embeds.append(analysis_embed)
            await interaction.edit_original_response(
                content=None, embeds=embeds, attachments=[file], view=self
            )


async def item_name_autocomplete(
    interaction: Interaction,
    current: str
) -> list[app_commands.Choice[str]]:
    """등록된 감시 아이템 목록에서 자동완성 제공"""
    items = await get_all_watch_items()
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


@app_commands.command(name="시세차트", description="아이템 경매장 시세를 캔들스틱 차트로 조회합니다")
@app_commands.describe(item_name="조회할 아이템 이름 (등록된 아이템에서 자동완성)")
@app_commands.autocomplete(item_name=item_name_autocomplete)
async def auction_chart(interaction: Interaction, item_name: str):
    logger.info(f"/시세차트 호출: 사용자={interaction.user.id}, 아이템={item_name}")
    await interaction.response.defer(thinking=True)

    # 감시 목록에서 아이템 확인
    watch_item = await get_watch_item_by_name(item_name)
    if not watch_item:
        all_items = await get_all_watch_items()
        matches = [
            item for item in all_items
            if item_name.lower() in item["item_name"].lower()
        ]
        if len(matches) == 1:
            watch_item = matches[0]
        elif len(matches) > 1:
            names = "\n".join(f"- {item['item_name']}" for item in matches)
            await interaction.followup.send(
                f"여러 아이템이 일치합니다. 자동완성에서 선택해주세요:\n{names}"
            )
            return
        else:
            await interaction.followup.send(
                "등록되지 않은 아이템입니다. `/시세등록`으로 먼저 등록해주세요."
            )
            return

    pref = _user_prefs.get(interaction.user.id, {})
    interval = pref.get("interval", 60)
    period = pref.get("period", 7)

    view = ChartControlView(
        watch_item["item_id"], watch_item["item_name"],
        interval_minutes=interval, period_days=period
    )

    result = await _build_chart(
        watch_item["item_id"], watch_item["item_name"],
        interval_minutes=interval, period_days=period
    )

    if isinstance(result, str):
        msg = await interaction.followup.send(content=result, view=view)
    else:
        embed, file, analysis_embed = result
        embeds = [embed]
        if analysis_embed:
            embeds.append(analysis_embed)
        msg = await interaction.followup.send(embeds=embeds, file=file, view=view)
    view.message = msg
