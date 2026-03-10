import discord
from discord import app_commands, Interaction, ui

from core.db import (
    get_all_watch_items, get_user_alerts,
    upsert_user_alert, delete_user_alert,
)
from core.logger import logger

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


def _format_value(alert_type: str, value: float) -> str:
    meta = ALERT_META[alert_type]
    if alert_type in ("new_high", "new_low"):
        return f"{int(value)}{meta['unit']}"
    elif alert_type in ("price_above", "price_below"):
        return f"{int(value):,}{meta['unit']}"
    elif alert_type in ("rsi_upper", "rsi_lower"):
        return f"{value:.0f}"
    else:
        return f"{value:.0f}{meta['unit']}"


def _mode_label(one_time: bool) -> str:
    return "1회" if one_time else "반복"


def _build_settings_embed(
    item_name: str, user_settings: list[dict]
) -> discord.Embed:
    settings_map = {
        s["alert_type"]: s for s in user_settings
    }

    embed = discord.Embed(
        title=f"알림 설정: {item_name}",
        color=0xFFA502
    )

    lines = []
    for at, label in ALERT_TYPE_LABELS.items():
        if at in settings_map:
            s = settings_map[at]
            val = _format_value(at, s["threshold_value"])
            mode = _mode_label(bool(s.get("one_time", 0)))
            lines.append(f"**{label}**: {val} [{mode}]")
        elif at in DEFAULT_THRESHOLDS:
            val = _format_value(at, DEFAULT_THRESHOLDS[at])
            lines.append(f"{label}: {val} (기본값)")
        else:
            lines.append(f"{label}: 미설정")

    embed.description = "\n".join(lines)
    embed.set_footer(
        text="버튼을 눌러 수치를 변경하세요. "
             "설정하면 DM으로 알림을 받습니다."
    )
    return embed


# ─── Modal: 수치 + 알림 방식 입력 ───

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
        default = ""
        if current_value is not None:
            if current_value == int(current_value):
                default = str(int(current_value))
            else:
                default = str(current_value)
        elif alert_type in DEFAULT_THRESHOLDS:
            default = str(int(DEFAULT_THRESHOLDS[alert_type]))

        self.value_input = ui.TextInput(
            label=meta["label"],
            placeholder=meta["hint"],
            default=default,
            required=True,
            max_length=20,
        )
        self.add_item(self.value_input)

        # 알림 방식 선택
        if current_one_time is not None:
            mode_default = "1회" if current_one_time else "반복"
        else:
            is_default_ot = DEFAULT_ONE_TIME.get(alert_type, False)
            mode_default = "1회" if is_default_ot else "반복"

        self.mode_input = ui.TextInput(
            label="알림 방식 (1회 또는 반복)",
            placeholder="1회 = 한번 울리면 자동 해제 / 반복 = 계속 유지",
            default=mode_default,
            required=True,
            max_length=10,
        )
        self.add_item(self.mode_input)

    async def on_submit(self, interaction: Interaction):
        # 수치 파싱
        raw = self.value_input.value.strip().replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            await interaction.response.send_message(
                "숫자를 입력해주세요.", ephemeral=True
            )
            return

        if value <= 0:
            await interaction.response.send_message(
                "0보다 큰 값을 입력해주세요.", ephemeral=True
            )
            return

        if self.alert_type in ("rsi_upper", "rsi_lower"):
            if not (0 < value <= 100):
                await interaction.response.send_message(
                    "RSI는 1~100 사이 값을 입력해주세요.",
                    ephemeral=True
                )
                return

        # 알림 방식 파싱
        mode_raw = self.mode_input.value.strip()
        if mode_raw in ("1회", "1", "once", "한번"):
            one_time = True
        elif mode_raw in ("반복", "0", "repeat", "계속"):
            one_time = False
        else:
            await interaction.response.send_message(
                "'1회' 또는 '반복'을 입력해주세요.",
                ephemeral=True
            )
            return

        await upsert_user_alert(
            interaction.user.id, self.item_id,
            self.alert_type, value, one_time
        )

        # 부모 뷰 갱신
        settings = await get_user_alerts(
            interaction.user.id, self.item_id
        )
        embed = _build_settings_embed(self.item_name, settings)
        self.parent_view.update_buttons(settings)
        await interaction.response.edit_message(
            embed=embed, view=self.parent_view
        )


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


# ─── View: 아이템 선택 ───

class ItemSelectView(ui.View):
    def __init__(self, items: list[dict], author_id: int):
        super().__init__(timeout=120)
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
            placeholder="알림을 설정할 아이템을 선택하세요",
            options=options
        )
        self.select.callback = self._select_callback
        self.add_item(self.select)

    async def _select_callback(self, interaction: Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "본인이 실행한 명령어만 응답할 수 있습니다.",
                ephemeral=True
            )
            return

        item = self._items_map[self.select.values[0]]
        settings = await get_user_alerts(
            interaction.user.id, item["item_id"]
        )
        embed = _build_settings_embed(item["item_name"], settings)
        view = AlertTypeView(
            item["item_id"], item["item_name"],
            interaction.user.id, settings
        )
        await interaction.response.edit_message(
            content=None, embed=embed, view=view
        )


# ─── View: 알림 해제용 아이템 선택 ───

class AlertRemoveSelectView(ui.View):
    def __init__(self, items_with_alerts: list[dict], author_id: int):
        super().__init__(timeout=120)
        self.author_id = author_id
        self._items_map = {}

        options = []
        seen = set()
        for s in items_with_alerts:
            iid = s["item_id"]
            if iid in seen:
                continue
            seen.add(iid)
            name = s.get("item_name") or iid
            self._items_map[iid] = name
            options.append(discord.SelectOption(
                label=name[:100], value=iid
            ))

        self.select = ui.Select(
            placeholder="알림을 해제할 아이템을 선택하세요",
            options=options[:25]
        )
        self.select.callback = self._select_callback
        self.add_item(self.select)

    async def _select_callback(self, interaction: Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "본인이 실행한 명령어만 응답할 수 있습니다.",
                ephemeral=True
            )
            return

        item_id = self.select.values[0]
        item_name = self._items_map[item_id]
        await delete_user_alert(interaction.user.id, item_id)
        await interaction.response.edit_message(
            content=f"**{item_name}**의 알림 설정을 모두 해제했습니다.",
            embed=None, view=None
        )


# ─── 슬래시 커맨드 ───

@app_commands.command(
    name="알림설정",
    description="아이템별 시세 알림을 내 기준에 맞게 설정합니다 (DM 알림)"
)
async def alert_settings_cmd(interaction: Interaction):
    logger.info(f"/알림설정 호출: 사용자={interaction.user.id}")
    await interaction.response.defer(thinking=True, ephemeral=True)

    items = await get_all_watch_items()
    if not items:
        await interaction.followup.send(
            "시세 추적 중인 아이템이 없습니다. "
            "`/시세등록`으로 먼저 아이템을 등록해주세요.",
            ephemeral=True
        )
        return

    view = ItemSelectView(items, interaction.user.id)
    await interaction.followup.send(
        "알림을 설정할 아이템을 선택하세요.",
        view=view, ephemeral=True
    )


@app_commands.command(
    name="알림목록",
    description="내 알림 설정 목록을 확인합니다"
)
async def alert_list_cmd(interaction: Interaction):
    logger.info(f"/알림목록 호출: 사용자={interaction.user.id}")

    settings = await get_user_alerts(interaction.user.id)
    if not settings:
        await interaction.response.send_message(
            "설정된 알림이 없습니다. `/알림설정`으로 추가해보세요.",
            ephemeral=True
        )
        return

    # 아이템별 그룹핑
    grouped = {}
    for s in settings:
        name = s.get("item_name") or s["item_id"]
        grouped.setdefault(name, []).append(s)

    embeds = []
    for item_name, alerts in grouped.items():
        lines = []
        for a in alerts:
            label = ALERT_TYPE_LABELS.get(
                a["alert_type"], a["alert_type"]
            )
            val = _format_value(a["alert_type"], a["threshold_value"])
            mode = _mode_label(bool(a.get("one_time", 0)))
            lines.append(f"**{label}**: {val} [{mode}]")

        embed = discord.Embed(
            title=item_name,
            description="\n".join(lines),
            color=0xFFA502
        )
        embeds.append(embed)

    await interaction.response.send_message(
        content=f"내 알림 설정 ({len(settings)}개)",
        embeds=embeds[:10],
        ephemeral=True
    )


@app_commands.command(
    name="알림해제",
    description="아이템의 알림 설정을 해제합니다"
)
async def alert_remove_cmd(interaction: Interaction):
    logger.info(f"/알림해제 호출: 사용자={interaction.user.id}")
    await interaction.response.defer(thinking=True, ephemeral=True)

    settings = await get_user_alerts(interaction.user.id)
    if not settings:
        await interaction.followup.send(
            "해제할 알림이 없습니다.", ephemeral=True
        )
        return

    view = AlertRemoveSelectView(settings, interaction.user.id)
    await interaction.followup.send(
        "알림을 해제할 아이템을 선택하세요.",
        view=view, ephemeral=True
    )
