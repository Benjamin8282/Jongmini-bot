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


def _get_korean_font():
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


# 모듈 로드 시 1회 초기화 (스레드 안전: 이후 rcParams 변경 없음)
_FONT_NAME = _get_korean_font()
_apply_dark_theme(_FONT_NAME)


def _gold_formatter(x, pos):
    """y축 골드 포맷: 100,000 → 100K, 1,000,000 → 1M"""
    if x >= 1_000_000:
        return f"{x / 1_000_000:.1f}M"
    elif x >= 1_000:
        return f"{x / 1_000:.0f}K"
    return f"{int(x)}"


def _calc_iqr_bounds(prices: list, n: int, median: float, multiplier: float) -> tuple[float, float]:
    """IQR 기반 이상치 필터링 경계값 계산."""
    q1 = prices[n // 4]
    q3 = prices[3 * n // 4]
    iqr = q3 - q1

    if iqr == 0:
        if median == 0:
            return float("-inf"), float("inf")
        return median * 0.2, median * 5.0

    lower_bound = q1 - multiplier * iqr
    upper_bound = q3 + multiplier * iqr
    if median > 0:
        lower_bound = min(lower_bound, median * 0.2)
        upper_bound = max(upper_bound, median * 5.0)
    return lower_bound, upper_bound


def _apply_iqr_filter(records: list[dict], lower: float, upper: float) -> list[dict]:
    """IQR 범위 내 기록만 필터링. 결과가 원본의 절반 미만이면 원본 반환."""
    filtered = [
        r for r in records
        if lower <= r["unit_price"] <= upper
    ]
    if len(filtered) < len(records) * 0.5:
        return records
    return filtered


def filter_price_outliers(
    records: list[dict], multiplier: float = 3.0
) -> list[dict]:
    """
    IQR 기반 이상치 거래 기록 제거.

    unit_price 기준으로 Q1 - multiplier*IQR ~ Q3 + multiplier*IQR 범위를
    벗어나는 기록을 제거한다. 데이터가 10건 미만이면 필터링하지 않음.
    """
    if len(records) < 10:
        return records

    prices = sorted(r["unit_price"] for r in records)
    n = len(prices)
    median = prices[n // 2]

    lower_bound, upper_bound = _calc_iqr_bounds(prices, n, median, multiplier)

    if lower_bound == float("-inf"):
        return records

    return _apply_iqr_filter(records, lower_bound, upper_bound)


def aggregate_to_ohlc(records: list[dict], interval_minutes: int = 60) -> pd.DataFrame:
    """
    원본 거래 기록을 시간대별 OHLC로 집계

    records: [{"sold_date": str, "unit_price": int, "count": int}, ...]
    interval_minutes: 캔들 간격 (분 단위)
    Returns: DataFrame with columns [Open, High, Low, Close, Volume]
    """
    if not records:
        return pd.DataFrame()

    # 이상치 제거 후 집계
    records = filter_price_outliers(records)

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


def _save_fig_to_buffer(fig) -> BytesIO:
    """fig를 PNG BytesIO로 저장하고 fig를 닫는다."""
    buf = BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=120,
                    facecolor=BG_COLOR, edgecolor="none")
        buf.seek(0)
        return buf
    finally:
        plt.close(fig)


def _add_legend(ax, loc="upper left", fontsize=8):
    """다크 테마 범례 추가."""
    handles, _labels = ax.get_legend_handles_labels()
    if not handles:
        return
    legend = ax.legend(
        loc=loc, fontsize=fontsize, frameon=True,
        facecolor=PANEL_COLOR, edgecolor=GRID_COLOR,
        labelcolor=TEXT_COLOR, framealpha=0.8
    )
    legend.get_frame().set_linewidth(0.5)


def _add_combined_legend(ax, handles, labels, loc="upper left", fontsize=9):
    """합쳐진 핸들/라벨로 다크 테마 범례 추가."""
    if not handles:
        return
    legend = ax.legend(
        handles, labels,
        loc=loc, fontsize=fontsize, frameon=True,
        facecolor=PANEL_COLOR, edgecolor=GRID_COLOR,
        labelcolor=TEXT_COLOR, framealpha=0.8
    )
    legend.get_frame().set_linewidth(0.5)


def _setup_grid(ax):
    """다크 테마 그리드 적용."""
    ax.grid(True, color=GRID_COLOR, linestyle="--",
            linewidth=0.5, alpha=0.5)


def _pct_color_arrow(pct: float) -> tuple[str, str]:
    """변동률에 따른 색상과 화살표 반환."""
    if pct > 0:
        return UP_COLOR, "▲"
    if pct < 0:
        return DOWN_COLOR, "▼"
    return "#888888", "−"


def _hide_axes_decorations(ax):
    """축 눈금 및 테두리를 숨긴다."""
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def _render_overview_row(ax, item, idx, n):
    """시세현황 차트의 개별 아이템 행 렌더링."""
    prices = item["prices"]
    color, arrow = _pct_color_arrow(item["change_pct"])

    ax.set_facecolor(PANEL_COLOR)
    ax.plot(prices, color=color, linewidth=2, alpha=0.9)
    ax.fill_between(range(len(prices)), prices, alpha=0.15, color=color)
    ax.axhline(y=prices[-1], color=color, linewidth=0.5,
               linestyle="--", alpha=0.4)

    ax.set_xlim(0, len(prices) - 1)
    _hide_axes_decorations(ax)

    _add_overview_labels(ax, item, color, arrow)

    if idx < n - 1:
        ax.axhline(y=ax.get_ylim()[0], color=GRID_COLOR,
                   linewidth=0.5, alpha=0.5)


def _add_overview_labels(ax, item, color, arrow):
    """시세현황 좌측/우측 라벨 추가."""
    pct = item["change_pct"]
    ax.text(-0.02, 0.5, item["name"],
            transform=ax.transAxes, fontsize=11, fontweight="bold",
            fontfamily=_FONT_NAME, color=TEXT_COLOR,
            va="center", ha="right")

    price_text = f"{int(item['current']):,}G"
    pct_text = f"{arrow} {abs(pct):.1f}%"
    ax.text(1.02, 0.65, price_text,
            transform=ax.transAxes, fontsize=11, fontweight="bold",
            fontfamily=_FONT_NAME, color=TEXT_COLOR,
            va="center", ha="left")
    ax.text(1.02, 0.30, pct_text,
            transform=ax.transAxes, fontsize=10,
            fontfamily=_FONT_NAME, color=color,
            va="center", ha="left")


def generate_overview_chart(items_data: list[dict]) -> BytesIO | None:
    """여러 아이템의 24시간 스파크라인을 다크 테마로 생성"""
    if not items_data:
        return None

    n = len(items_data)
    row_height = 1.4
    fig, axes = plt.subplots(
        n, 1, figsize=(11, row_height * n + 0.8),
        facecolor=BG_COLOR
    )
    if n == 1:
        axes = [axes]

    for idx, (ax, item) in enumerate(zip(axes, items_data)):
        _render_overview_row(ax, item, idx, n)

    fig.subplots_adjust(left=0.22, right=0.82, hspace=0.3,
                        top=0.95, bottom=0.05)

    return _save_fig_to_buffer(fig)


def _plot_comparison_price_axes(ax_price, ohlc_a, ohlc_b, name_a, name_b, color_a, color_b):
    """비교 차트의 가격 듀얼 Y축 플롯."""
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
    return ax_b


def _add_correlation_badge(ax_price, correlation):
    """상관계수 뱃지 추가."""
    if correlation is None:
        return
    badge_color = "#2ed573" if correlation >= 0.3 else "#ff4757" if correlation <= -0.3 else "#888888"
    ax_price.text(
        0.98, 0.95, f"r = {correlation:.2f}",
        transform=ax_price.transAxes, fontsize=11, fontweight="bold",
        color="white", ha="right", va="top",
        bbox=dict(boxstyle="round,pad=0.3", facecolor=badge_color, alpha=0.8)
    )


def _plot_comparison_volume(ax_vol, ohlc_a, ohlc_b, name_a, name_b, color_a, color_b):
    """비교 차트의 하단 거래량 바 플롯."""
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
    ax_vol.set_ylabel("거래량", fontsize=9, color="#888888", fontfamily=_FONT_NAME)


def generate_comparison_chart(
    name_a: str, ohlc_a: pd.DataFrame,
    name_b: str, ohlc_b: pd.DataFrame,
    interval_label: str = "1시간",
    correlation: float | None = None,
) -> BytesIO | None:
    """두 아이템의 종가를 듀얼 Y축 라인 차트로 비교"""
    if ohlc_a.empty and ohlc_b.empty:
        return None

    fig, (ax_price, ax_vol) = plt.subplots(
        2, 1, figsize=(13, 7),
        gridspec_kw={"height_ratios": [4, 1]},
        facecolor=BG_COLOR
    )

    color_a = UP_COLOR
    color_b = ACCENT

    ax_b = _plot_comparison_price_axes(ax_price, ohlc_a, ohlc_b, name_a, name_b, color_a, color_b)

    # 범례 합치기
    handles_a, labels_a = ax_price.get_legend_handles_labels()
    handles_b, labels_b = ax_b.get_legend_handles_labels()
    _add_combined_legend(ax_price, handles_a + handles_b, labels_a + labels_b)

    _add_correlation_badge(ax_price, correlation)

    # 타이틀
    fig.text(0.06, 0.96, f"{name_a}  vs  {name_b}",
             fontsize=15, fontweight="bold", fontfamily=_FONT_NAME,
             color=TEXT_COLOR, va="top")
    fig.text(0.06, 0.92, interval_label,
             fontsize=10, fontfamily=_FONT_NAME,
             color="#888888", va="top")

    _plot_comparison_volume(ax_vol, ohlc_a, ohlc_b, name_a, name_b, color_a, color_b)

    # 그리드
    for ax in [ax_price, ax_vol]:
        _setup_grid(ax)
    ax_b.grid(False)

    fig.subplots_adjust(hspace=0.15, left=0.08, right=0.92, top=0.88, bottom=0.08)

    return _save_fig_to_buffer(fig)


def _build_candlestick_style(font_name: str) -> dict:
    """캔들스틱 차트의 mpf 스타일 생성."""
    mc = mpf.make_marketcolors(
        up=UP_COLOR, down=DOWN_COLOR,
        edge={"up": UP_COLOR, "down": DOWN_COLOR},
        wick={"up": UP_COLOR, "down": DOWN_COLOR},
        volume={"up": VOLUME_UP, "down": VOLUME_DOWN},
        ohlc="inherit"
    )
    return mpf.make_mpf_style(
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


_MA_LINES = [
    (5, "단기추세(5)"),
    (10, "심리(10)"),
    (20, "수급(20)"),
    (60, "경기(60)"),
]
_MA_COLORS = ["#ff6348", "#ffd32a", "#2ed573", "#a55eea"]


def _get_active_ma_lines(candle_count: int) -> list[tuple]:
    """캔들 수 이상의 이동평균선 설정만 필터링."""
    return [(n, label, color) for (n, label), color
            in zip(_MA_LINES, _MA_COLORS) if candle_count >= n]


def _build_mav_kwargs(candle_count: int) -> dict:
    """이동평균선 kwargs 생성."""
    active = _get_active_ma_lines(candle_count)
    if not active:
        return {}
    mav = tuple(n for n, _, _ in active)
    mav_colors = [c for _, _, c in active]
    return {"mav": mav, "mavcolors": mav_colors}


def _add_candlestick_legend(ax_price, candle_count):
    """캔들스틱 차트에 이동평균선 범례 추가."""
    active = _get_active_ma_lines(candle_count)
    if not active:
        return
    handles = [
        plt.Line2D([0], [0], color=c, linewidth=2, alpha=0.8)
        for _, _, c in active
    ]
    labels = [label for _, label, _ in active]
    _add_combined_legend(ax_price, handles, labels, fontsize=8)


def generate_candlestick_chart(
    item_name: str,
    ohlc_df: pd.DataFrame,
    interval_label: str = "1시간"
) -> BytesIO | None:
    """OHLC DataFrame을 다크 테마 캔들스틱 차트 이미지로 변환"""
    if ohlc_df.empty:
        return None

    candle_count = len(ohlc_df)
    mav_kwargs = _build_mav_kwargs(candle_count)

    fig, axes = mpf.plot(
        ohlc_df,
        type="candle",
        style=_build_candlestick_style(_FONT_NAME),
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
             fontsize=16, fontweight="bold", fontfamily=_FONT_NAME,
             color=TEXT_COLOR, va="top")
    fig.text(0.06, 0.91, interval_label,
             fontsize=10, fontfamily=_FONT_NAME,
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

    _add_candlestick_legend(ax_price, candle_count)

    # 하단 볼륨 라벨
    ax_volume.set_ylabel("거래량", fontsize=9, color="#888888",
                         fontfamily=_FONT_NAME)

    return _save_fig_to_buffer(fig)


def _draw_changepoints(ax, x, changepoints):
    """변화점 수직선 + 체제 배경색 그리기."""
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
                fontfamily=_FONT_NAME, fontweight="bold",
                zorder=4)


def _draw_outlier_markers(ax, x, y, outlier_dates):
    """이상치 마커 그리기."""
    ol_dates = pd.to_datetime(outlier_dates)
    for od in ol_dates:
        idx_match = np.where(x == od)[0]
        if len(idx_match) > 0:
            idx = idx_match[0]
            ax.plot(x[idx], y[idx], "v", color="#ff6348",
                    markersize=7, zorder=5, alpha=0.8)


def _draw_current_value_dot(ax, x, y, baseline=100):
    """현재값 점 + 라벨 그리기."""
    if len(y) == 0:
        return
    last_val = y[-1]
    dot_color = UP_COLOR if last_val >= baseline else DOWN_COLOR
    ax.plot(x[-1], last_val, "o", color=dot_color,
            markersize=8, zorder=5)
    ax.annotate(
        f"{last_val:.1f}%",
        xy=(x[-1], last_val),
        xytext=(10, 10), textcoords="offset points",
        fontsize=11, fontweight="bold", color=dot_color,
        fontfamily=_FONT_NAME
    )


def _draw_activity_lines(ax, x, y, raw_index, dates):
    """활동지수 메인 라인, 기준선, 채우기, 원본 라인."""
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


def _setup_activity_axes(ax):
    """활동지수 차트 축 설정."""
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, p: f"{v:.0f}%")
    )
    _setup_grid(ax)


def _build_activity_subtitle(item_count: int, changepoints: list[str] | None) -> str:
    """활동지수 차트 부제목 생성."""
    subtitle = f"바스켓 {item_count}개 아이템 | 100% = 30일 평균"
    if changepoints:
        subtitle += f" | 체제 전환 {len(changepoints)}건"
    return subtitle


def _draw_activity_overlays(ax, x, y, changepoints, outlier_dates):
    """활동지수 차트의 변화점/이상치 오버레이 그리기."""
    if changepoints:
        _draw_changepoints(ax, x, changepoints)
    if outlier_dates:
        _draw_outlier_markers(ax, x, y, outlier_dates)


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

    fig, ax = plt.subplots(figsize=(13, 5), facecolor=BG_COLOR)
    ax.set_facecolor(PANEL_COLOR)

    x = pd.to_datetime(dates)
    y = np.array(index_values, dtype=float)

    _draw_activity_overlays(ax, x, y, changepoints, outlier_dates)
    _draw_activity_lines(ax, x, y, raw_index, dates)
    _draw_current_value_dot(ax, x, y, baseline=100)

    # 타이틀
    fig.text(0.06, 0.96, "활동지수 (거래량 기반 추정)",
             fontsize=15, fontweight="bold", fontfamily=_FONT_NAME,
             color=TEXT_COLOR, va="top")

    subtitle = _build_activity_subtitle(item_count, changepoints)
    fig.text(0.06, 0.91, subtitle,
             fontsize=10, fontfamily=_FONT_NAME,
             color="#888888", va="top")

    _add_legend(ax, loc="upper right")
    _setup_activity_axes(ax)

    fig.subplots_adjust(left=0.08, right=0.95, top=0.85, bottom=0.12)

    return _save_fig_to_buffer(fig)


def _draw_dunspy_lines(ax, x, y, current):
    """던스피 메인 라인, 기준선, 채우기."""
    # 1000 기준선
    ax.axhline(y=1000, color="#888888", linewidth=1,
               linestyle="--", alpha=0.4)

    # 그라데이션 채우기 (1000 기준 위/아래)
    ax.fill_between(x, y, 1000, where=(y >= 1000),
                    color=UP_COLOR, alpha=0.12, interpolate=True)
    ax.fill_between(x, y, 1000, where=(y < 1000),
                    color=DOWN_COLOR, alpha=0.12, interpolate=True)

    # 메인 라인
    line_color = UP_COLOR if current >= 1000 else DOWN_COLOR
    ax.plot(x, y, color=line_color, linewidth=2.5, alpha=0.9)


def _draw_dunspy_high_low(ax, x, y):
    """던스피 기간 고/저 수평선 + 라벨."""
    high_val = max(y)
    low_val = min(y)
    ax.axhline(y=high_val, color=UP_COLOR, linewidth=0.7,
               linestyle=":", alpha=0.5)
    ax.axhline(y=low_val, color=DOWN_COLOR, linewidth=0.7,
               linestyle=":", alpha=0.5)
    ax.text(x[0], high_val, f" H {high_val:.1f}",
            fontsize=8, color=UP_COLOR, va="bottom",
            fontfamily=_FONT_NAME, alpha=0.7)
    ax.text(x[0], low_val, f" L {low_val:.1f}",
            fontsize=8, color=DOWN_COLOR, va="top",
            fontfamily=_FONT_NAME, alpha=0.7)


def _draw_dunspy_current(ax, x, y, current, change, change_pct):
    """던스피 현재값 점 + 라벨."""
    if len(y) == 0:
        return
    dot_color = UP_COLOR if change >= 0 else DOWN_COLOR
    arrow = "▲" if change > 0 else "▼" if change < 0 else "−"
    ax.plot(x[-1], current, "o", color=dot_color,
            markersize=10, zorder=5)
    ax.annotate(
        f"{current:.1f}  {arrow}{abs(change_pct):.2f}%",
        xy=(x[-1], current),
        xytext=(10, 12), textcoords="offset points",
        fontsize=12, fontweight="bold", color=dot_color,
        fontfamily=_FONT_NAME,
        bbox=dict(boxstyle="round,pad=0.3",
                  facecolor=PANEL_COLOR, edgecolor=dot_color,
                  alpha=0.8)
    )


def generate_dunspy_chart(
    dates: list[str], index_values: list[float],
    current: float = 0, change: float = 0,
    change_pct: float = 0, item_count: int = 0,
    base_date: str = "",
) -> BytesIO | None:
    """던스피(DUNSPY) 지수 차트. 증시 스타일."""
    if not dates or not index_values:
        return None

    fig, ax = plt.subplots(figsize=(13, 5), facecolor=BG_COLOR)
    ax.set_facecolor(PANEL_COLOR)

    x = pd.to_datetime(dates)
    y = np.array(index_values, dtype=float)

    _draw_dunspy_lines(ax, x, y, current)
    _draw_dunspy_high_low(ax, x, y)
    _draw_dunspy_current(ax, x, y, current, change, change_pct)

    # 타이틀
    fig.text(0.06, 0.96, "DUNSPY 던스피 종합지수",
             fontsize=16, fontweight="bold", fontfamily=_FONT_NAME,
             color=TEXT_COLOR, va="top")
    subtitle = (
        f"바스켓 {item_count}종목 | 기준일 {base_date} = 1,000"
    )
    fig.text(0.06, 0.91, subtitle,
             fontsize=10, fontfamily=_FONT_NAME,
             color="#888888", va="top")

    # 축 설정
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, p: f"{v:,.0f}")
    )
    _setup_grid(ax)

    fig.subplots_adjust(left=0.08, right=0.92, top=0.85, bottom=0.12)

    return _save_fig_to_buffer(fig)
