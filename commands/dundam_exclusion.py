import discord
from discord import app_commands, Interaction
from discord.ui import View, Button
from core.db import get_all_adventures, set_adventure_exclusion
from core.models import SERVER_MAP
from core.logger import logger


class AdventureExclusionView(View):
    """모험단 검색 제외 설정 UI"""

    def __init__(self, adventures: list[dict]):
        super().__init__(timeout=300)  # 5분 타임아웃
        self.adventures = adventures
        self.states = {}  # {(adventure_name, server_id): is_excluded}

        # 초기 상태 설정
        for adv in adventures:
            key = (adv['adventure_name'], adv['server_id'])
            self.states[key] = bool(adv['is_excluded'])

        # Discord는 한 View에 최대 25개 버튼만 허용
        # 모험단이 24개 이하면 각각 버튼, 초과하면 Select Menu 사용 필요
        if len(adventures) <= 24:
            self._add_toggle_buttons()

        # 저장 버튼 추가
        self.add_item(SaveButton())

    def _add_toggle_buttons(self):
        """각 모험단마다 토글 버튼 추가"""
        for adv in self.adventures:
            key = (adv['adventure_name'], adv['server_id'])
            button = AdventureToggleButton(
                adventure_name=adv['adventure_name'],
                server_id=adv['server_id'],
                is_excluded=self.states[key]
            )
            self.add_item(button)

    def get_embed(self) -> discord.Embed:
        """현재 상태를 보여주는 Embed 생성"""
        embed = discord.Embed(
            title="던담 검색 모험단 설정",
            description="체크된 모험단(✅)만 던담순위에 표시됩니다.\n버튼을 클릭하여 상태를 변경하고 저장 버튼을 눌러주세요.",
            color=discord.Color.blue()
        )

        status_text = ""
        for adv in self.adventures:
            key = (adv['adventure_name'], adv['server_id'])
            is_excluded = self.states[key]
            server_name = SERVER_MAP.get(adv['server_id'], adv['server_id'])

            emoji = "❌" if is_excluded else "✅"
            status_text += f"{emoji} **{adv['adventure_name']}** ({server_name})\n"

        embed.add_field(name="모험단 목록", value=status_text or "등록된 모험단이 없습니다.", inline=False)
        return embed


class AdventureToggleButton(Button):
    """개별 모험단의 포함/제외 토글 버튼"""

    def __init__(self, adventure_name: str, server_id: str, is_excluded: bool):
        self.adventure_name = adventure_name
        self.server_id = server_id

        # 버튼 레이블 설정 (최대 80자)
        server_name = SERVER_MAP.get(server_id, server_id)
        label = f"{adventure_name} ({server_name})"
        if len(label) > 80:
            label = label[:77] + "..."

        # 현재 상태에 따라 스타일 설정
        style = discord.ButtonStyle.danger if is_excluded else discord.ButtonStyle.success
        emoji = "❌" if is_excluded else "✅"

        super().__init__(
            label=label,
            style=style,
            emoji=emoji,
            custom_id=f"toggle_{adventure_name}_{server_id}"
        )

    async def callback(self, interaction: Interaction):
        """버튼 클릭 시 상태 토글"""
        view: AdventureExclusionView = self.view
        key = (self.adventure_name, self.server_id)

        # 상태 토글
        view.states[key] = not view.states[key]
        is_excluded = view.states[key]

        # 버튼 스타일 업데이트
        self.style = discord.ButtonStyle.danger if is_excluded else discord.ButtonStyle.success
        self.emoji = "❌" if is_excluded else "✅"

        # UI 업데이트
        await interaction.response.edit_message(embed=view.get_embed(), view=view)
        logger.info(f"모험단 토글: {self.adventure_name} ({self.server_id}) -> {'제외' if is_excluded else '포함'}")


class SaveButton(Button):
    """변경사항 저장 버튼"""

    def __init__(self):
        super().__init__(
            label="💾 저장",
            style=discord.ButtonStyle.primary,
            custom_id="save_exclusions",
            row=4  # 마지막 줄에 배치
        )

    async def callback(self, interaction: Interaction):
        """저장 버튼 클릭 시 DB에 저장"""
        view: AdventureExclusionView = self.view

        # 모든 상태를 DB에 저장
        for (adventure_name, server_id), is_excluded in view.states.items():
            await set_adventure_exclusion(adventure_name, server_id, is_excluded)

        # 성공 메시지
        embed = discord.Embed(
            title="✅ 저장 완료",
            description="던담 검색 모험단 설정이 저장되었습니다.",
            color=discord.Color.green()
        )

        # View 비활성화
        for item in view.children:
            item.disabled = True

        # 메시지 즉시 업데이트 (defer 없이)
        await interaction.response.edit_message(embed=embed, view=view)
        logger.info("모험단 제외 설정 저장 완료")


@app_commands.command(name="던담검색제외", description="던담순위에서 검색할 모험단을 설정합니다.")
async def dundam_exclusion(interaction: Interaction):
    """던담 검색 모험단 설정 커맨드"""
    await interaction.response.defer(thinking=True)

    # 모든 모험단 조회
    adventures = await get_all_adventures()

    if not adventures:
        await interaction.followup.send("등록된 모험단이 없습니다.")
        return

    if len(adventures) > 24:
        await interaction.followup.send(
            f"⚠️ 모험단이 너무 많습니다 ({len(adventures)}개). "
            "현재 버전에서는 최대 24개까지만 지원합니다."
        )
        return

    # UI 생성 및 전송
    view = AdventureExclusionView(adventures)
    embed = view.get_embed()

    await interaction.followup.send(embed=embed, view=view)
    logger.info(f"던담검색제외 커맨드 실행: {len(adventures)}개 모험단")
