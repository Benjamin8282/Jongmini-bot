import platform
from io import BytesIO

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import mplfinance as mpf  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

# 다크 테마 색상 팔레트
BG_COLOR = "#1a1a2e"
PANEL_COLOR = "#16213e"
TEXT_COLOR = "#e0e0e0"
GRID_COLOR = "#2a2a4a"
UP_COLOR = "#ff4757"
DOWN_COLOR = "#3498ff"
UP_FILL = "#ff475740"
DOWN_FILL = "#3498ff40"
VOLUME_UP = "#ff475780"
VOLUME_DOWN = "#3498ff80"
ACCENT = "#ffd32a"


def get_korean_font():
    if platform.system() == "Windows":
        return "Malgun Gothic"
    else:
        return "NanumGothic"


def _apply_dark_theme(font_name: str):
    """matplotlib 전역 다크 테마 설정."""
    matplotlib.rcParams.update({
        "axes.unicode_minus": False,
        "font.family": font_name,
        "figure.facecolor": BG_COLOR,
        "axes.facecolor": PANEL_COLOR,
        "axes.edgecolor": GRID_COLOR,
        "axes.labelcolor": TEXT_COLOR,
        "text.color": TEXT_COLOR,
        "xtick.color": TEXT_COLOR,
        "ytick.color": TEXT_COLOR,
    })


def _gold_formatter(x, pos):
    """y축 골드 포맷: 100,000 → 100K, 1,000,000 → 1M"""
    if x >= 1_000_000:
        return f"{x / 1_000_000:.1f}M"
    elif x >= 1_000:
        return f"{x / 1_000:.0f}K"
    return f"{int(x)}"


def aggregate_to_ohlc(records: list[dict], interval_minutes: int = 60) -> pd.DataFrame:
    """
    원본 거래 기록을 시간대별 OHLC로 집계

    records: [{"sold_date": str, "unit_price": int, "count": int}, ...]
    interval_minutes: 캔들 간격 (분 단위)
    Returns: DataFrame with columns [Open, High, Low, Close, Volume]
    """
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["datetime"] = pd.to_datetime(df["sold_date"])
    df = df.sort_values("datetime")
    df = df.set_index("datetime")

    if interval_minutes >= 1440:
        freq = f"{interval_minutes // 1440}D"
    elif interval_minutes >= 60:
        freq = f"{interval_minutes // 60}h"
    else:
        freq = f"{interval_minutes}min"

    ohlc = df["unit_price"].resample(freq).ohlc()
    volume = df["count"].resample(freq).sum()

    result = ohlc.join(volume.rename("volume"))
    result = result.dropna()

    return result


def generate_overview_chart(items_data: list[dict]) -> BytesIO | None:
    """여러 아이템의 24시간 스파크라인을 다크 테마로 생성"""
    if not items_data:
        return None

    font_name = get_korean_font()
    _apply_dark_theme(font_name)

    n = len(items_data)
    row_height = 1.4
    fig, axes = plt.subplots(
        n, 1, figsize=(11, row_height * n + 0.8),
        facecolor=BG_COLOR
    )
    if n == 1:
        axes = [axes]

    for idx, (ax, item) in enumerate(zip(axes, items_data)):
        prices = item["prices"]
        pct = item["change_pct"]
        color = UP_COLOR if pct > 0 else DOWN_COLOR if pct < 0 else "#888888"
        arrow = "▲" if pct > 0 else "▼" if pct < 0 else "−"

        ax.set_facecolor(PANEL_COLOR)

        # 그래프 라인 + 그라데이션 채우기
        ax.plot(prices, color=color, linewidth=2, alpha=0.9)
        ax.fill_between(range(len(prices)), prices, alpha=0.15, color=color)

        # 현재가 수평 점선
        ax.axhline(y=prices[-1], color=color, linewidth=0.5,
                   linestyle="--", alpha=0.4)

        ax.set_xlim(0, len(prices) - 1)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

        # 좌측 라벨: 아이템명
        ax.text(-0.02, 0.5, item["name"],
                transform=ax.transAxes, fontsize=11, fontweight="bold",
                fontfamily=font_name, color=TEXT_COLOR,
                va="center", ha="right")

        # 우측 라벨: 가격 + 변동률
        price_text = f"{int(item['current']):,}G"
        pct_text = f"{arrow} {abs(pct):.1f}%"
        ax.text(1.02, 0.65, price_text,
                transform=ax.transAxes, fontsize=11, fontweight="bold",
                fontfamily=font_name, color=TEXT_COLOR,
                va="center", ha="left")
        ax.text(1.02, 0.30, pct_text,
                transform=ax.transAxes, fontsize=10,
                fontfamily=font_name, color=color,
                va="center", ha="left")

        # 행 사이 구분선
        if idx < n - 1:
            ax.axhline(y=ax.get_ylim()[0], color=GRID_COLOR,
                       linewidth=0.5, alpha=0.5)

    fig.subplots_adjust(left=0.22, right=0.82, hspace=0.3,
                        top=0.95, bottom=0.05)

    buf = BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                    facecolor=BG_COLOR, edgecolor="none")
        buf.seek(0)
        return buf
    finally:
        plt.close(fig)


def generate_comparison_chart(
    name_a: str, ohlc_a: pd.DataFrame,
    name_b: str, ohlc_b: pd.DataFrame,
    interval_label: str = "1시간",
    correlation: float | None = None,
) -> BytesIO | None:
    """두 아이템의 종가를 듀얼 Y축 라인 차트로 비교"""
    if ohlc_a.empty and ohlc_b.empty:
        return None

    font_name = get_korean_font()
    _apply_dark_theme(font_name)

    fig, (ax_price, ax_vol) = plt.subplots(
        2, 1, figsize=(13, 7),
        gridspec_kw={"height_ratios": [4, 1]},
        facecolor=BG_COLOR
    )

    color_a = UP_COLOR       # #ff4757
    color_b = ACCENT         # #ffd32a

    # 좌측 Y축: 아이템 A
    ax_price.set_facecolor(PANEL_COLOR)
    if not ohlc_a.empty:
        ax_price.plot(ohlc_a.index, ohlc_a["close"],
                      color=color_a, linewidth=2.5, label=name_a, alpha=0.9)
        ax_price.fill_between(ohlc_a.index, ohlc_a["close"],
                              alpha=0.1, color=color_a)
    ax_price.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, p: f"{int(x):,}")
    )
    ax_price.tick_params(axis="y", colors=color_a)

    # 우측 Y축: 아이템 B
    ax_b = ax_price.twinx()
    if not ohlc_b.empty:
        ax_b.plot(ohlc_b.index, ohlc_b["close"],
                  color=color_b, linewidth=1.8, label=name_b,
                  alpha=0.9, linestyle="--")
        ax_b.fill_between(ohlc_b.index, ohlc_b["close"],
                          alpha=0.1, color=color_b)
    ax_b.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, p: f"{int(x):,}")
    )
    ax_b.tick_params(axis="y", colors=color_b)

    # 범례 합치기
    handles_a, labels_a = ax_price.get_legend_handles_labels()
    handles_b, labels_b = ax_b.get_legend_handles_labels()
    if handles_a or handles_b:
        legend = ax_price.legend(
            handles_a + handles_b, labels_a + labels_b,
            loc="upper left", fontsize=9, frameon=True,
            facecolor=PANEL_COLOR, edgecolor=GRID_COLOR,
            labelcolor=TEXT_COLOR, framealpha=0.8
        )
        legend.get_frame().set_linewidth(0.5)

    # 상관계수 뱃지
    if correlation is not None:
        badge_color = "#2ed573" if correlation >= 0.3 else "#ff4757" if correlation <= -0.3 else "#888888"
        ax_price.text(
            0.98, 0.95, f"r = {correlation:.2f}",
            transform=ax_price.transAxes, fontsize=11, fontweight="bold",
            color="white", ha="right", va="top",
            bbox=dict(boxstyle="round,pad=0.3", facecolor=badge_color, alpha=0.8)
        )

    # 타이틀
    fig.text(0.06, 0.96, f"{name_a}  vs  {name_b}",
             fontsize=15, fontweight="bold", fontfamily=font_name,
             color=TEXT_COLOR, va="top")
    fig.text(0.06, 0.92, interval_label,
             fontsize=10, fontfamily=font_name,
             color="#888888", va="top")

    # 하단 거래량 바
    ax_vol.set_facecolor(PANEL_COLOR)
    bar_width_td = pd.Timedelta(minutes=15)
    if not ohlc_a.empty and len(ohlc_a) >= 2:
        bar_width_td = (ohlc_a.index[-1] - ohlc_a.index[0]) / len(ohlc_a) * 0.35

    if not ohlc_a.empty:
        ax_vol.bar(ohlc_a.index - bar_width_td / 2, ohlc_a["volume"],
                   width=bar_width_td, color=color_a, alpha=0.5, label=name_a)
    if not ohlc_b.empty:
        ax_vol.bar(ohlc_b.index + bar_width_td / 2, ohlc_b["volume"],
                   width=bar_width_td, color=color_b, alpha=0.5, label=name_b)

    ax_vol.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, p: f"{int(x):,}")
    )
    ax_vol.set_ylabel("거래량", fontsize=9, color="#888888", fontfamily=font_name)

    # 그리드
    for ax in [ax_price, ax_vol]:
        ax.grid(True, color=GRID_COLOR, linestyle="--", linewidth=0.5, alpha=0.5)
    ax_b.grid(False)

    fig.subplots_adjust(hspace=0.15, left=0.08, right=0.92, top=0.88, bottom=0.08)

    buf = BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                    facecolor=BG_COLOR, edgecolor="none")
        buf.seek(0)
        return buf
    finally:
        plt.close(fig)


def generate_candlestick_chart(
    item_name: str,
    ohlc_df: pd.DataFrame,
    interval_label: str = "1시간"
) -> BytesIO | None:
    """OHLC DataFrame을 다크 테마 캔들스틱 차트 이미지로 변환"""
    if ohlc_df.empty:
        return None

    font_name = get_korean_font()
    _apply_dark_theme(font_name)

    # 다크 테마 캔들 스타일
    mc = mpf.make_marketcolors(
        up=UP_COLOR, down=DOWN_COLOR,
        edge={"up": UP_COLOR, "down": DOWN_COLOR},
        wick={"up": UP_COLOR, "down": DOWN_COLOR},
        volume={"up": VOLUME_UP, "down": VOLUME_DOWN},
        ohlc="inherit"
    )
    style = mpf.make_mpf_style(
        marketcolors=mc,
        facecolor=PANEL_COLOR,
        figcolor=BG_COLOR,
        gridstyle="--",
        gridcolor=GRID_COLOR,
        y_on_right=True,
        rc={
            "font.family": font_name,
            "axes.labelcolor": TEXT_COLOR,
            "xtick.color": TEXT_COLOR,
            "ytick.color": TEXT_COLOR,
        }
    )

    # 이동평균선
    MA_LINES = [
        (5, "단기추세(5)"),
        (10, "심리(10)"),
        (20, "수급(20)"),
        (60, "경기(60)"),
    ]
    MA_COLORS = ["#ff6348", "#ffd32a", "#2ed573", "#a55eea"]
    candle_count = len(ohlc_df)
    mav = tuple(n for n, _ in MA_LINES if candle_count >= n)

    mav_kwargs = {}
    if mav:
        mav_kwargs["mav"] = mav
        mav_kwargs["mavcolors"] = [
            c for (n, _), c in zip(MA_LINES, MA_COLORS) if candle_count >= n
        ]

    fig, axes = mpf.plot(
        ohlc_df,
        type="candle",
        style=style,
        title="",
        ylabel="",
        ylabel_lower="",
        volume=True,
        figsize=(13, 7),
        returnfig=True,
        tight_layout=False,
        scale_padding={"left": 0.4, "right": 0.8, "top": 0.6, "bottom": 0.5},
        **mav_kwargs
    )

    ax_price = axes[0]
    ax_volume = axes[2]  # mplfinance volume panel

    # 타이틀 커스텀
    fig.text(0.06, 0.95, item_name,
             fontsize=16, fontweight="bold", fontfamily=font_name,
             color=TEXT_COLOR, va="top")
    fig.text(0.06, 0.91, interval_label,
             fontsize=10, fontfamily=font_name,
             color="#888888", va="top")

    # 현재가 표시 (우측)
    last_close = ohlc_df["close"].iloc[-1]
    prev_close = ohlc_df["close"].iloc[-2] if len(ohlc_df) >= 2 else last_close
    price_color = UP_COLOR if last_close >= prev_close else DOWN_COLOR
    ax_price.axhline(y=last_close, color=price_color, linewidth=0.8,
                     linestyle="--", alpha=0.5)

    # y축 골드 포맷
    ax_price.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, p: f"{int(x):,}")
    )
    ax_volume.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, p: f"{int(x):,}")
    )

    # 범례
    if mav:
        legend_labels = [label for n, label in MA_LINES if candle_count >= n]
        legend_colors = [
            c for (n, _), c in zip(MA_LINES, MA_COLORS) if candle_count >= n
        ]
        handles = [
            plt.Line2D([0], [0], color=c, linewidth=2, alpha=0.8)
            for c in legend_colors
        ]
        legend = ax_price.legend(
            handles, legend_labels,
            loc="upper left", fontsize=8, frameon=True,
            facecolor=PANEL_COLOR, edgecolor=GRID_COLOR,
            labelcolor=TEXT_COLOR, framealpha=0.8
        )
        legend.get_frame().set_linewidth(0.5)

    # 하단 볼륨 라벨
    ax_volume.set_ylabel("거래량", fontsize=9, color="#888888",
                         fontfamily=font_name)

    buf = BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                    facecolor=BG_COLOR, edgecolor="none")
        buf.seek(0)
        return buf
    finally:
        plt.close(fig)


def generate_activity_chart(
    dates: list[str], index_values: list[float],
    item_count: int = 0,
    changepoints: list[str] | None = None,
    outlier_dates: list[str] | None = None,
    raw_index: list[float] | None = None,
) -> BytesIO | None:
    """
    활동지수 라인 차트 생성.
    100% 기준선, 변화점 수직선, 이상치 마커, 원본 비교선 포함.
    """
    if not dates or not index_values:
        return None

    font_name = get_korean_font()
    _apply_dark_theme(font_name)

    fig, ax = plt.subplots(figsize=(13, 5), facecolor=BG_COLOR)
    ax.set_facecolor(PANEL_COLOR)

    x = pd.to_datetime(dates)
    y = np.array(index_values, dtype=float)

    # 변화점 수직선 + 체제 배경색
    if changepoints:
        cp_dates = pd.to_datetime(changepoints)
        regime_colors = ["#2a2a4a", "#1e3a2a"]
        boundaries = [x[0]] + sorted(cp_dates) + [x[-1]]
        for i in range(len(boundaries) - 1):
            color = regime_colors[i % len(regime_colors)]
            ax.axvspan(boundaries[i], boundaries[i + 1],
                       alpha=0.3, color=color, zorder=0)
        for cp in cp_dates:
            ax.axvline(x=cp, color="#ff6348", linewidth=1.5,
                       linestyle="--", alpha=0.7, zorder=3)
            ax.text(cp, ax.get_ylim()[1] if ax.get_ylim()[1] > 100
                    else 120, "CP",
                    fontsize=8, color="#ff6348", ha="center",
                    fontfamily=font_name, fontweight="bold",
                    zorder=4)

    # 100% 기준선
    ax.axhline(y=100, color="#888888", linewidth=1,
               linestyle="--", alpha=0.6)

    # 원본 지수 (정제 전) 반투명 라인
    if raw_index and len(raw_index) == len(dates):
        y_raw = np.array(raw_index, dtype=float)
        ax.plot(x, y_raw, color="#888888", linewidth=1,
                alpha=0.35, linestyle=":", label="원본 (정제 전)")

    # 100% 위/아래 색분할 채우기
    ax.fill_between(x, y, 100, where=(y >= 100),
                    color=UP_COLOR, alpha=0.15, interpolate=True)
    ax.fill_between(x, y, 100, where=(y < 100),
                    color=DOWN_COLOR, alpha=0.15, interpolate=True)

    # 메인 라인
    ax.plot(x, y, color=ACCENT, linewidth=2.5, alpha=0.9,
            label="정제된 지수")

    # 이상치 마커
    if outlier_dates:
        ol_dates = pd.to_datetime(outlier_dates)
        for od in ol_dates:
            idx_match = np.where(x == od)[0]
            if len(idx_match) > 0:
                idx = idx_match[0]
                ax.plot(x[idx], y[idx], "v", color="#ff6348",
                        markersize=7, zorder=5, alpha=0.8)

    # 현재값 점
    if len(y) > 0:
        last_val = y[-1]
        dot_color = UP_COLOR if last_val >= 100 else DOWN_COLOR
        ax.plot(x[-1], last_val, "o", color=dot_color,
                markersize=8, zorder=5)
        ax.annotate(
            f"{last_val:.1f}%",
            xy=(x[-1], last_val),
            xytext=(10, 10), textcoords="offset points",
            fontsize=11, fontweight="bold", color=dot_color,
            fontfamily=font_name
        )

    # 타이틀
    fig.text(0.06, 0.96, "활동지수 (거래량 기반 추정)",
             fontsize=15, fontweight="bold", fontfamily=font_name,
             color=TEXT_COLOR, va="top")

    subtitle = f"바스켓 {item_count}개 아이템 | 100% = 30일 평균"
    if changepoints:
        subtitle += f" | 체제 전환 {len(changepoints)}건"
    fig.text(0.06, 0.91, subtitle,
             fontsize=10, fontfamily=font_name,
             color="#888888", va="top")

    # 범례
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        legend = ax.legend(
            loc="upper right", fontsize=8, frameon=True,
            facecolor=PANEL_COLOR, edgecolor=GRID_COLOR,
            labelcolor=TEXT_COLOR, framealpha=0.8
        )
        legend.get_frame().set_linewidth(0.5)

    # 축 설정
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, p: f"{v:.0f}%")
    )
    ax.grid(True, color=GRID_COLOR, linestyle="--",
            linewidth=0.5, alpha=0.5)

    fig.subplots_adjust(left=0.08, right=0.95, top=0.85, bottom=0.12)

    buf = BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                    facecolor=BG_COLOR, edgecolor="none")
        buf.seek(0)
        return buf
    finally:
        plt.close(fig)
