import time
import aiohttp
import discord
from discord import app_commands, Interaction
from discord.ui import View, Button
from core.db import get_active_characters
from core.dundam_api import fetch_all_with_rate_limit


def format_score_korean(num: int) -> str:
    if num >= 100_000_000:
        return f"{num // 100_000_000}억 {num % 100_000_000 // 10_000}만"
    elif num >= 10_000:
        return f"{num // 10_000}만 {num % 10_000}"
    else:
        return f"{num}"


class DundamRankingView(View):
    """던담 랭킹 페이지네이션 View"""

    def __init__(self, ranked_characters: list[dict], timestamp: str):
        super().__init__(timeout=300)  # 5분 타임아웃
        self.ranked_characters = ranked_characters
        self.timestamp = timestamp
        self.current_page = 0
        self.items_per_page = 20
        self.total_pages = (len(ranked_characters) + self.items_per_page - 1) // self.items_per_page

        # 버튼 추가
        self.add_item(PreviousButton())
        self.add_item(NextButton())

        # 버튼 상태 업데이트
        self.update_buttons()

    def update_buttons(self):
        """현재 페이지에 따라 버튼 활성화/비활성화"""
        for item in self.children:
            if isinstance(item, PreviousButton):
                item.disabled = (self.current_page == 0)
            elif isinstance(item, NextButton):
                item.disabled = (self.current_page >= self.total_pages - 1)

    def get_embed(self) -> discord.Embed:
        """현재 페이지의 Embed 생성"""
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.ranked_characters))
        page_characters = self.ranked_characters[start_idx:end_idx]

        embed = discord.Embed(title="던담 데미지 순위", color=discord.Color.gold())
        embed.set_footer(text=f"기준 시각: {self.timestamp} | 페이지: {self.current_page + 1}/{self.total_pages}")

        description = ""
        for i, char in enumerate(page_characters, start=start_idx + 1):
            score_kor = format_score_korean(char['damage'])
            char_name = char.get('character_name', '알 수 없음')
            adv_name = char.get('adventure_name', '알 수 없음')
            description += f"**{i}위** **{char_name}** ({adv_name})\n"
            description += f"**점수:** {score_kor}\n\n"

        if not description:
            description = "던담 랭킹 정보를 가져올 수 있는 캐릭터가 없습니다."

        embed.description = description
        return embed


class PreviousButton(Button):
    """이전 페이지 버튼"""

    def __init__(self):
        super().__init__(
            label="◀ 이전",
            style=discord.ButtonStyle.primary,
            custom_id="previous_page"
        )

    async def callback(self, interaction: Interaction):
        view: DundamRankingView = self.view
        if view.current_page > 0:
            view.current_page -= 1
            view.update_buttons()
            await interaction.response.edit_message(embed=view.get_embed(), view=view)


class NextButton(Button):
    """다음 페이지 버튼"""

    def __init__(self):
        super().__init__(
            label="다음 ▶",
            style=discord.ButtonStyle.primary,
            custom_id="next_page"
        )

    async def callback(self, interaction: Interaction):
        view: DundamRankingView = self.view
        if view.current_page < view.total_pages - 1:
            view.current_page += 1
            view.update_buttons()
            await interaction.response.edit_message(embed=view.get_embed(), view=view)


@app_commands.command(name="던담순위", description="등록된 모든 캐릭터의 던담 랭킹을 조회합니다.")
async def dundam_ranking(interaction: Interaction):
    await interaction.response.defer(thinking=True)

    characters = await get_active_characters()
    if not characters:
        await interaction.followup.send("등록된 캐릭터가 없습니다.")
        return

    async with aiohttp.ClientSession() as session:
        results = await fetch_all_with_rate_limit(session, characters, limit_per_second=5)

    ranked_characters = sorted([r for r in results if r], key=lambda x: x['damage'], reverse=True)

    if not ranked_characters:
        await interaction.followup.send("던담 랭킹 정보를 가져올 수 있는 캐릭터가 없습니다.")
        return

    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    view = DundamRankingView(ranked_characters, timestamp)
    embed = view.get_embed()

    await interaction.followup.send(embed=embed, view=view)
