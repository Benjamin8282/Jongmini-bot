"""/자캐커미션(화풍변환) · /자캐장면커미션(장면연출) — DNF 캐릭터 AI 일러스트화.

  · /자캐커미션      = 화풍변환(style): 원본 자세 유지, 화풍 선택(애니/수채화/반실사).
  · /자캐장면커미션  = 장면연출(scene): 사용자가 입력한 장면/배경으로 자유 연출(반실사).

모드별로 필요한 입력만 노출하려고 커맨드를 분리(discord 는 옵션 동적 숨김 불가).
제한: 본인 등록 캐릭터만, 일 3장, 쿨다운 60초. 결과에 AI 생성·출처 고지.
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

STYLE_CHOICES = [
    app_commands.Choice(name="반실사", value="painterly"),
    app_commands.Choice(name="애니", value="anime"),
    app_commands.Choice(name="수채화", value="watercolor"),
]


async def _run_generation(send, character: dict, mode: str, style_key: str,
                          scene: str | None, user_id: int):
    """이미지 fetch → 한도 원자 선점 → 모드별 생성 → 결과 embed 전송.

    send: 결과를 보낼 콜러블(interaction.followup.send). mode: "scene" | "style".
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


async def _character_autocomplete(interaction: Interaction,
                                  current: str) -> list[app_commands.Choice[str]]:
    """character 파라미터 자동완성 — 본인 등록 캐릭터 중 입력어를 포함하는 항목을 제시."""
    try:
        chars = await get_characters_by_user(interaction.user.id)
    except Exception:
        return []
    cur = current.strip().lower()
    matched = [c for c in chars if cur in c["character_name"].lower()] if cur else chars
    return [
        app_commands.Choice(name=c["character_name"], value=c["character_name"])
        for c in matched[:25]
    ]


async def _check_cooldown_and_limit(interaction: Interaction, user_id: int) -> bool:
    """사용량/쿨다운 빠른 체크(UX용 조기 거부). 막히면 메시지 보내고 True, 통과면 False."""
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    usage = await get_commission_usage(user_id, today)
    if usage["count"] >= DAILY_LIMIT:
        await interaction.followup.send(
            f"오늘은 이미 {DAILY_LIMIT}장을 모두 사용했어요. 내일 다시 시도해 주세요.", ephemeral=True)
        return True
    if usage["last_used"]:
        try:
            elapsed = (now - datetime.fromisoformat(usage["last_used"])).total_seconds()
            if elapsed < COOLDOWN_SEC:
                await interaction.followup.send(
                    f"잠시만요! {int(COOLDOWN_SEC - elapsed)}초 후에 다시 시도해 주세요.", ephemeral=True)
                return True
        except (ValueError, TypeError):
            pass
    return False


async def _resolve_and_generate(interaction: Interaction, mode_val: str,
                                style_key: str, scene: str | None, character: str | None):
    """대상 캐릭터 결정 → 생성 또는 선택 UI 폴백. 두 커맨드 공유."""
    user_id = interaction.user.id
    characters = await get_characters_by_user(user_id)
    if not characters:
        await interaction.followup.send("먼저 `/등록`으로 캐릭터를 등록해 주세요.", ephemeral=True)
        return

    target = None
    if character:
        cs = character.strip()
        # 정확 일치 → 공백/대소문자 무시 폴백
        target = next((c for c in characters if c["character_name"] == cs), None)
        if not target:
            target = next(
                (c for c in characters if c["character_name"].strip().lower() == cs.lower()), None)
    elif len(characters) == 1:
        target = characters[0]

    if target:
        await _run_generation(interaction.followup.send, target, mode_val, style_key, scene, user_id)
    else:
        # 이름 매칭 실패 또는 여러 캐릭터 → 선택 UI 폴백(막다른 "찾지 못했어요" 제거)
        msg = "커미션할 캐릭터를 선택하세요."
        if character:
            msg = f"'{character}'을(를) 정확히 찾지 못했어요. 아래 목록에서 선택해 주세요."
        view = CommissionCharacterSelect(characters, user_id, mode_val, style_key, scene)
        view.message = await interaction.followup.send(msg, view=view, ephemeral=True)


@app_commands.command(name="자캐커미션", description="등록한 DNF 캐릭터를 AI로 화풍 변환합니다 (원본 자세 유지)")
@app_commands.describe(
    style="화풍 선택 (기본: 반실사)",
    character="대상 캐릭터 이름 (자동완성 — 미지정 시 등록 캐릭터에서 선택)",
)
@app_commands.choices(style=STYLE_CHOICES)
@app_commands.autocomplete(character=_character_autocomplete)
async def character_commission(
    interaction: Interaction,
    style: app_commands.Choice[str] = None,
    character: str = None,
):
    user_id = interaction.user.id
    logger.info(f"/자캐커미션(화풍변환) 호출: 사용자={user_id}")
    # noinspection PyUnresolvedReferences
    await interaction.response.defer(thinking=True)
    if await _check_cooldown_and_limit(interaction, user_id):
        return
    style_key = style.value if style else "painterly"
    await _resolve_and_generate(interaction, "style", style_key, None, character)


@app_commands.command(name="자캐장면커미션",
                      description="등록한 DNF 캐릭터를 원하는 장면/배경으로 AI 연출합니다 (반실사)")
@app_commands.describe(
    scene="장면 묘사 (영문 권장, 예: sitting on a throne in a castle)",
    character="대상 캐릭터 이름 (자동완성 — 미지정 시 등록 캐릭터에서 선택)",
)
@app_commands.autocomplete(character=_character_autocomplete)
async def character_scene_commission(
    interaction: Interaction,
    scene: str,
    character: str = None,
):
    user_id = interaction.user.id
    logger.info(f"/자캐장면커미션(장면연출) 호출: 사용자={user_id}")
    # noinspection PyUnresolvedReferences
    await interaction.response.defer(thinking=True)
    if len(scene) > SCENE_MAX_LEN:
        await interaction.followup.send(
            f"`scene`이 너무 길어요. {SCENE_MAX_LEN}자 이내로 입력해 주세요.", ephemeral=True)
        return
    if await _check_cooldown_and_limit(interaction, user_id):
        return
    await _resolve_and_generate(interaction, "scene", "painterly", scene, character)
