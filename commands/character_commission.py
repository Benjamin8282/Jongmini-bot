"""/자캐커미션 — 등록한 DNF 캐릭터를 AWS Bedrock 으로 AI 일러스트화.

2가지 모드:
  · 장면연출(scene): 사용자가 입력한 장면/배경으로 자유 연출(화풍 반실사 고정).
  · 화풍변환(style): 원본 자세를 유지한 채 화풍만 변환(애니/수채화/반실사).

제한: 본인 등록 캐릭터만, 일 3장, 쿨다운 60초. 결과에 AI 생성·출처 고지.
사용량은 생성 시작 전 원자적 선점(reserve)으로 한도 우회를 방지한다.
"""
from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands, Interaction, Embed, ui
from discord.utils import escape_markdown

from core.logger import logger
from core.models import SERVER_MAP
from core.dnf_api import get_character_image_bytes
from core.db import (
    get_characters_by_user, get_commission_usage, reserve_commission_usage,
)
from core.bedrock import generate_scene_commission, generate_style_commission

KST = ZoneInfo("Asia/Seoul")
DAILY_LIMIT = 3
COOLDOWN_SEC = 60
SCENE_MAX_LEN = 300

KEY_TO_KR = {"painterly": "반실사", "anime": "애니", "watercolor": "수채화"}

MODE_CHOICES = [
    app_commands.Choice(name="장면연출 (자세·배경 자유, 반실사)", value="scene"),
    app_commands.Choice(name="화풍변환 (원본 자세 유지, 화풍 선택)", value="style"),
]
STYLE_CHOICES = [
    app_commands.Choice(name="반실사", value="painterly"),
    app_commands.Choice(name="애니", value="anime"),
    app_commands.Choice(name="수채화", value="watercolor"),
]


async def _run_generation(send, character: dict, mode: str, style_key: str,
                          scene: str | None, user_id: int):
    """이미지 fetch → 한도 원자 선점 → 모드별 생성 → 결과 embed 전송.

    send: 결과를 보낼 콜러블(interaction.followup.send).
    """
    char_name = character["character_name"]

    # 1) 이미지 fetch (Bedrock 비용 발생 전 — 실패해도 사용량 차감 없음)
    img = await get_character_image_bytes(character["server_id"], character["character_id"])
    if not img:
        await send(content="캐릭터 이미지를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.", ephemeral=True)
        return

    # 2) 일일 한도 원자적 선점 (TOCTOU race 방지). 이 시점 이후 1장 소모 확정.
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    if not await reserve_commission_usage(user_id, today, now.isoformat(), DAILY_LIMIT):
        await send(
            content=f"오늘은 이미 {DAILY_LIMIT}장을 모두 사용했어요. 내일 다시 시도해 주세요.",
            ephemeral=True)
        return

    # 3) 모드별 생성
    try:
        if mode == "scene":
            result = await generate_scene_commission(img, scene)
            desc_line = f"**장면**: {escape_markdown(scene)}\n**화풍**: 반실사"
        else:
            result = await generate_style_commission(img, style_key)
            desc_line = f"**화풍**: {KEY_TO_KR.get(style_key, style_key)} · 원본 자세 유지"
    except Exception as e:
        logger.error(f"커미션 생성 실패: 캐릭터={char_name}, 모드={mode}, 에러={e}")
        await send(
            content="이미지 생성 중 오류가 발생했어요. (오류 시에도 횟수가 소모될 수 있어요)",
            ephemeral=True)
        return

    # 4) 결과 전송 (AI·출처 고지)
    usage = await get_commission_usage(user_id, today)
    remaining = max(0, DAILY_LIMIT - usage["count"])
    file = discord.File(BytesIO(result), filename="commission.png")
    embed = Embed(
        title=f"🎨 {char_name} · 자캐 커미션",
        description=f"{desc_line}\n오늘 남은 횟수: {remaining}/{DAILY_LIMIT}",
        color=discord.Color.purple(),
    )
    embed.set_image(url="attachment://commission.png")
    embed.set_footer(
        text="AI 생성 · 비공식 팬 콘텐츠 · 원본 © NEOPLE · 결과가 아쉬우면 다시 시도(매번 다른 그림)")
    await send(embed=embed, file=file)
    logger.info(f"커미션 전송 완료: 사용자={user_id}, 캐릭터={char_name}, 모드={mode}")


class CommissionCharacterSelect(ui.View):
    """등록 캐릭터가 여러 개일 때 대상 캐릭터를 고르는 드롭다운."""

    def __init__(self, characters: list[dict], author_id: int,
                 mode: str, style_key: str, scene: str | None):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.mode = mode
        self.style_key = style_key
        self.scene = scene
        self.message = None  # 커맨드에서 전송 후 주입 (timeout 시 편집용)
        self._map = {c["character_id"]: c for c in characters[:25]}

        options = [
            discord.SelectOption(
                label=c["character_name"],
                description=(
                    f'{c.get("job_grow_name") or ""} - '
                    f'{SERVER_MAP.get(c["server_id"], c["server_id"])}'
                )[:100],
                value=c["character_id"],
            ) for c in characters[:25]
        ]
        self.select = ui.Select(placeholder="커미션할 캐릭터를 선택하세요", options=options)
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: Interaction):
        if interaction.user.id != self.author_id:
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message("본인이 실행한 명령어만 조작할 수 있어요.", ephemeral=True)
            return
        char = self._map[self.select.values[0]]
        # noinspection PyUnresolvedReferences
        await interaction.response.defer(thinking=True)
        await _run_generation(
            interaction.followup.send, char, self.mode, self.style_key, self.scene, self.author_id)
        self.stop()

    async def on_timeout(self):
        """타임아웃 시 드롭다운을 비활성화해 무음 상태를 시각적으로 표시."""
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass
        self.stop()


@app_commands.command(name="자캐커미션", description="등록한 DNF 캐릭터를 AI 일러스트로 재해석합니다")
@app_commands.describe(
    mode="모드 선택 (장면연출 / 화풍변환)",
    style="화풍변환 모드의 화풍 (기본: 반실사)",
    scene="장면연출 모드의 장면 묘사 (영문 권장, 예: sitting on a throne)",
    character="대상 캐릭터 이름 (미지정 시 등록 캐릭터에서 선택)",
)
@app_commands.choices(mode=MODE_CHOICES, style=STYLE_CHOICES)
async def character_commission(
    interaction: Interaction,
    mode: app_commands.Choice[str],
    style: app_commands.Choice[str] = None,
    scene: str = None,
    character: str = None,
):
    user_id = interaction.user.id
    logger.info(f"/자캐커미션 호출: 사용자={user_id}, 모드={mode.value}")
    # noinspection PyUnresolvedReferences
    await interaction.response.defer(thinking=True)

    mode_val = mode.value
    style_key = style.value if style else "painterly"

    # 모드별 필수 입력/길이 검증
    if mode_val == "scene":
        if not scene:
            await interaction.followup.send(
                "장면연출 모드는 `scene`을 입력해야 해요. 예: `sitting on a throne in a grand castle`",
                ephemeral=True)
            return
        if len(scene) > SCENE_MAX_LEN:
            await interaction.followup.send(
                f"`scene`이 너무 길어요. {SCENE_MAX_LEN}자 이내로 입력해 주세요.", ephemeral=True)
            return

    # 사용량/쿨다운 빠른 체크 (UX용 조기 거부 — 최종 게이트는 _run_generation 의 reserve)
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    usage = await get_commission_usage(user_id, today)
    if usage["count"] >= DAILY_LIMIT:
        await interaction.followup.send(
            f"오늘은 이미 {DAILY_LIMIT}장을 모두 사용했어요. 내일 다시 시도해 주세요.", ephemeral=True)
        return
    if usage["last_used"]:
        try:
            elapsed = (now - datetime.fromisoformat(usage["last_used"])).total_seconds()
            if elapsed < COOLDOWN_SEC:
                await interaction.followup.send(
                    f"잠시만요! {int(COOLDOWN_SEC - elapsed)}초 후에 다시 시도해 주세요.", ephemeral=True)
                return
        except (ValueError, TypeError):
            pass

    # 대상 캐릭터 결정
    characters = await get_characters_by_user(user_id)
    if not characters:
        await interaction.followup.send("먼저 `/등록`으로 캐릭터를 등록해 주세요.", ephemeral=True)
        return

    target = None
    if character:
        target = next((c for c in characters if c["character_name"] == character), None)
        if not target:
            await interaction.followup.send(
                f"등록된 캐릭터 중 '{character}'을(를) 찾지 못했어요.", ephemeral=True)
            return
    elif len(characters) == 1:
        target = characters[0]

    if target:
        await _run_generation(interaction.followup.send, target, mode_val, style_key, scene, user_id)
    else:
        view = CommissionCharacterSelect(characters, user_id, mode_val, style_key, scene)
        view.message = await interaction.followup.send(
            "커미션할 캐릭터를 선택하세요.", view=view, ephemeral=True)
