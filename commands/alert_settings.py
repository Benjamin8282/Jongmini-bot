import discord
from discord import app_commands, Interaction, ui

from core.db import (
    get_all_watch_items, get_user_alerts,
    upsert_user_alert, delete_user_alert,
    get_watch_item_by_name,
)
from core.logger import logger
from commands.auction_chart import item_name_autocomplete

ALERT_TYPE_LABELS = {
    "surge": "급등",
    "crash": "급락",
    "new_high": "신고가",
    "new_low": "신저가",
    "volume_spike": "거래량 폭증",
    "rsi_upper": "RSI 과매수",
    "rsi_lower": "RSI 과매도",
    "price_above": "지정가 이상",
    "price_below": "지정가 이하",
}

DEFAULT_THRESHOLDS = {
    "surge": 30.0,
    "crash": 30.0,
    "new_high": 14,
    "new_low": 14,
    "volume_spike": 10.0,
    "rsi_upper": 70.0,
    "rsi_lower": 30.0,
}

# 알림 종류별 기본 1회성 여부 (지정가만 기본 1회)
DEFAULT_ONE_TIME = {
    "price_above": True,
    "price_below": True,
}

# 알림 종류별 단위 & 안내
ALERT_META = {
    "surge": {"unit": "%", "label": "변동률 (%)", "hint": "예: 15"},
    "crash": {"unit": "%", "label": "변동률 (%)", "hint": "예: 15"},
    "new_high": {"unit": "일", "label": "기간 (일)", "hint": "예: 7"},
    "new_low": {"unit": "일", "label": "기간 (일)", "hint": "예: 7"},
    "volume_spike": {"unit": "배", "label": "배수", "hint": "예: 5"},
    "rsi_upper": {"unit": "", "label": "RSI 값 (0~100)", "hint": "예: 75"},
    "rsi_lower": {"unit": "", "label": "RSI 값 (0~100)", "hint": "예: 25"},
    "price_above": {"unit": "G", "label": "가격 (골드)", "hint": "예: 1000000"},
    "price_below": {"unit": "G", "label": "가격 (골드)", "hint": "예: 500000"},
}

_FORMAT_DISPATCH = {
    "new_high": lambda v, meta: f"{int(v)}{meta['unit']}",
    "new_low": lambda v, meta: f"{int(v)}{meta['unit']}",
    "price_above": lambda v, meta: f"{int(v):,}{meta['unit']}",
    "price_below": lambda v, meta: f"{int(v):,}{meta['unit']}",
    "rsi_upper": lambda v, meta: f"{v:.0f}",
    "rsi_lower": lambda v, meta: f"{v:.0f}",
}


def _format_value(alert_type: str, value: float) -> str:
    meta = ALERT_META[alert_type]
    formatter = _FORMAT_DISPATCH.get(alert_type)
    if formatter:
        return formatter(value, meta)
    return f"{value:.0f}{meta['unit']}"


def _mode_label(one_time: bool) -> str:
    return "1회" if one_time else "반복"


def _setting_line(at: str, label: str, settings_map: dict) -> str:
    """알림 타입별 설정 라인 생성."""
    if at in settings_map:
        s = settings_map[at]
        val = _format_value(at, s["threshold_value"])
        mode = _mode_label(bool(s.get("one_time", 0)))
        return f"**{label}**: {val} [{mode}]"
    if at in DEFAULT_THRESHOLDS:
        val = _format_value(at, DEFAULT_THRESHOLDS[at])
        return f"{label}: {val} (기본값)"
    return f"{label}: 미설정"


def _build_settings_embed(
    item_name: str, user_settings: list[dict]
) -> discord.Embed:
    settings_map = {s["alert_type"]: s for s in user_settings}
    embed = discord.Embed(
        title=f"알림 설정: {item_name}",
        color=0xFFA502
    )
    lines = [_setting_line(at, label, settings_map) for at, label in ALERT_TYPE_LABELS.items()]
    embed.description = "\n".join(lines)
    embed.set_footer(
        text="버튼을 눌러 수치를 변경하세요. "
             "설정하면 DM으로 알림을 받습니다."
    )
    return embed


# ─── Modal: 수치 + 알림 방식 입력 ───

def _resolve_default_value(alert_type: str, current_value: float | None) -> str:
    if current_value is not None:
        if current_value == int(current_value):
            return str(int(current_value))
        return str(current_value)
    if alert_type in DEFAULT_THRESHOLDS:
        return str(int(DEFAULT_THRESHOLDS[alert_type]))
    return ""


def _resolve_mode_default(alert_type: str, current_one_time: bool | None) -> str:
    if current_one_time is not None:
        return "1회" if current_one_time else "반복"
    is_default_ot = DEFAULT_ONE_TIME.get(alert_type, False)
    return "1회" if is_default_ot else "반복"


_ONE_TIME_VALUES = {"1회", "1", "once", "한번"}
_REPEAT_VALUES = {"반복", "0", "repeat", "계속"}


def _parse_mode(mode_raw: str) -> bool | None:
    """알림 방식 파싱. True=1회, False=반복, None=잘못된 입력."""
    cleaned = mode_raw.strip()
    if cleaned in _ONE_TIME_VALUES:
        return True
    if cleaned in _REPEAT_VALUES:
        return False
    return None


def _validate_value(alert_type: str, value: float) -> str | None:
    """값 검증. 에러 메시지 또는 None."""
    if value <= 0:
        return "0보다 큰 값을 입력해주세요."
    if alert_type in ("rsi_upper", "rsi_lower") and not (0 < value <= 100):
        return "RSI는 1~100 사이 값을 입력해주세요."
    return None


class ThresholdInputModal(ui.Modal):
    def __init__(
        self, alert_type: str, item_id: str,
        item_name: str, current_value: float | None,
        current_one_time: bool | None,
        parent_view: "AlertTypeView"
    ):
        label = ALERT_TYPE_LABELS[alert_type]
        super().__init__(title=f"{label} 설정")
        self.alert_type = alert_type
        self.item_id = item_id
        self.item_name = item_name
        self.parent_view = parent_view

        meta = ALERT_META[alert_type]
        default = _resolve_default_value(alert_type, current_value)

        self.value_input = ui.TextInput(
            label=meta["label"],
            placeholder=meta["hint"],
            default=default,
            required=True,
            max_length=20,
        )
        self.add_item(self.value_input)

        mode_default = _resolve_mode_default(alert_type, current_one_time)
        self.mode_input = ui.TextInput(
            label="알림 방식 (1회 또는 반복)",
            placeholder="1회 = 한번 울리면 자동 해제 / 반복 = 계속 유지",
            default=mode_default,
            required=True,
            max_length=10,
        )
        self.add_item(self.mode_input)

    async def on_submit(self, interaction: Interaction):
        raw = self.value_input.value.strip().replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            await interaction.response.send_message("숫자를 입력해주세요.", ephemeral=True)
            return

        err = _validate_value(self.alert_type, value)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return

        one_time = _parse_mode(self.mode_input.value)
        if one_time is None:
            await interaction.response.send_message("'1회' 또는 '반복'을 입력해주세요.", ephemeral=True)
            return

        await upsert_user_alert(
            interaction.user.id, self.item_id,
            self.alert_type, value, one_time
        )

        settings = await get_user_alerts(interaction.user.id, self.item_id)
        embed = _build_settings_embed(self.item_name, settings)
        self.parent_view.update_buttons(settings)
        await interaction.response.edit_message(embed=embed, view=self.parent_view)


# ─── View: 알림 종류 버튼 그리드 ───

class AlertTypeView(ui.View):
    def __init__(
        self, item_id: str, item_name: str,
        user_id: int, user_settings: list[dict]
    ):
        super().__init__(timeout=300)
        self.item_id = item_id
        self.item_name = item_name
        self.user_id = user_id
        self._build_buttons(user_settings)

    def _build_buttons(self, user_settings: list[dict]):
        settings_map = {
            s["alert_type"]: s for s in user_settings
        }

        button_defs = [
            ("surge", 0, discord.ButtonStyle.danger),
            ("crash", 0, discord.ButtonStyle.primary),
            ("new_high", 0, discord.ButtonStyle.secondary),
            ("new_low", 0, discord.ButtonStyle.secondary),
            ("volume_spike", 1, discord.ButtonStyle.secondary),
            ("rsi_upper", 1, discord.ButtonStyle.secondary),
            ("rsi_lower", 1, discord.ButtonStyle.secondary),
            ("price_above", 2, discord.ButtonStyle.success),
            ("price_below", 2, discord.ButtonStyle.success),
        ]

        for at, row, style in button_defs:
            label = ALERT_TYPE_LABELS[at]
            cur_val = None
            cur_ot = None

            if at in settings_map:
                s = settings_map[at]
                cur_val = s["threshold_value"]
                cur_ot = bool(s.get("one_time", 0))
                val = _format_value(at, cur_val)
                mode = _mode_label(cur_ot)
                label = f"{label} ({val}|{mode})"
            elif at in DEFAULT_THRESHOLDS:
                val = _format_value(at, DEFAULT_THRESHOLDS[at])
                label = f"{label} ({val})"

            btn = ui.Button(
                label=label[:80], style=style,
                custom_id=f"alert_{at}", row=row
            )
            btn.callback = self._make_callback(at, cur_val, cur_ot)
            self.add_item(btn)

        # 초기화 버튼
        reset_btn = ui.Button(
            label="전체 초기화", style=discord.ButtonStyle.danger,
            custom_id="alert_reset", row=3
        )
        reset_btn.callback = self._reset_callback
        self.add_item(reset_btn)

    def update_buttons(self, user_settings: list[dict]):
        self.clear_items()
        self._build_buttons(user_settings)

    def _make_callback(
        self, alert_type: str,
        current_value: float | None,
        current_one_time: bool | None
    ):
        async def callback(interaction: Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message(
                    "본인이 실행한 명령어만 응답할 수 있습니다.",
                    ephemeral=True
                )
                return
            modal = ThresholdInputModal(
                alert_type, self.item_id, self.item_name,
                current_value, current_one_time, self
            )
            await interaction.response.send_modal(modal)
        return callback

    async def _reset_callback(self, interaction: Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "본인이 실행한 명령어만 응답할 수 있습니다.",
                ephemeral=True
            )
            return
        await delete_user_alert(self.user_id, self.item_id)
        embed = _build_settings_embed(self.item_name, [])
        self.update_buttons([])
        await interaction.response.edit_message(
            embed=embed, view=self
        )


# ─── Autocomplete ───

async def _user_alert_item_autocomplete(
    interaction: Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """사용자가 알림 설정한 아이템 중에서 자동완성"""
    settings = await get_user_alerts(interaction.user.id)
    if not settings:
        return []
    seen = set()
    items = []
    for s in settings:
        name = s.get("item_name") or s["item_id"]
        if name in seen:
            continue
        seen.add(name)
        items.append(name)
    if current:
        current_lower = current.lower()
        items = [n for n in items if current_lower in n.lower()]
    return [
        app_commands.Choice(name=n, value=n) for n in items[:25]
    ]


# ─── 슬래시 커맨드 ───

@app_commands.command(
    name="시세알림",
    description="아이템별 시세 알림을 내 기준에 맞게 설정합니다 (DM 알림)"
)
@app_commands.describe(item_name="알림을 설정할 아이템 이름")
@app_commands.autocomplete(item_name=item_name_autocomplete)
async def alert_settings_cmd(interaction: Interaction, item_name: str):
    logger.info(f"/시세알림 호출: 사용자={interaction.user.id}, 아이템={item_name}")
    await interaction.response.defer(thinking=True, ephemeral=True)

    watch_item = await get_watch_item_by_name(item_name)
    if not watch_item:
        all_items = await get_all_watch_items()
        matches = [i for i in all_items if item_name.lower() in i["item_name"].lower()]
        if len(matches) == 1:
            watch_item = matches[0]
        elif matches:
            names = "\n".join(f"- {i['item_name']}" for i in matches[:10])
            await interaction.followup.send(
                f"여러 아이템이 일치합니다. 자동완성에서 선택해주세요:\n{names}",
                ephemeral=True
            )
            return
        else:
            await interaction.followup.send(
                "등록되지 않은 아이템입니다. `/시세등록`으로 먼저 등록해주세요.",
                ephemeral=True
            )
            return

    settings = await get_user_alerts(interaction.user.id, watch_item["item_id"])
    embed = _build_settings_embed(watch_item["item_name"], settings)
    view = AlertTypeView(
        watch_item["item_id"], watch_item["item_name"],
        interaction.user.id, settings
    )
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)


def _build_alert_embed(item_name: str, alerts: list[dict]) -> discord.Embed:
    lines = []
    for a in alerts:
        label = ALERT_TYPE_LABELS.get(a["alert_type"], a["alert_type"])
        val = _format_value(a["alert_type"], a["threshold_value"])
        mode = _mode_label(bool(a.get("one_time", 0)))
        lines.append(f"**{label}**: {val} [{mode}]")
    return discord.Embed(
        title=item_name,
        description="\n".join(lines),
        color=0xFFA502
    )


def _group_alerts(settings: list[dict]) -> dict[str, list[dict]]:
    grouped = {}
    for s in settings:
        name = s.get("item_name") or s["item_id"]
        grouped.setdefault(name, []).append(s)
    return grouped


@app_commands.command(
    name="시세알림목록",
    description="내 시세 알림 설정 목록을 확인합니다"
)
async def alert_list_cmd(interaction: Interaction):
    logger.info(f"/시세알림목록 호출: 사용자={interaction.user.id}")

    settings = await get_user_alerts(interaction.user.id)
    if not settings:
        await interaction.response.send_message(
            "설정된 알림이 없습니다. `/시세알림`으로 추가해보세요.",
            ephemeral=True
        )
        return

    grouped = _group_alerts(settings)
    embeds = [_build_alert_embed(name, alerts) for name, alerts in grouped.items()]

    await interaction.response.send_message(
        content=f"내 알림 설정 ({len(settings)}개)",
        embeds=embeds[:10],
        ephemeral=True
    )


@app_commands.command(
    name="시세알림해제",
    description="아이템의 시세 알림 설정을 해제합니다"
)
@app_commands.describe(item_name="알림을 해제할 아이템 이름")
@app_commands.autocomplete(item_name=_user_alert_item_autocomplete)
async def alert_remove_cmd(interaction: Interaction, item_name: str):
    logger.info(f"/시세알림해제 호출: 사용자={interaction.user.id}, 아이템={item_name}")
    await interaction.response.defer(thinking=True, ephemeral=True)

    watch_item = await get_watch_item_by_name(item_name)
    if not watch_item:
        await interaction.followup.send(
            "등록되지 않은 아이템입니다.", ephemeral=True
        )
        return

    await delete_user_alert(interaction.user.id, watch_item["item_id"])
    await interaction.followup.send(
        f"**{watch_item['item_name']}**의 알림 설정을 모두 해제했습니다.",
        ephemeral=True
    )
