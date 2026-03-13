from datetime import datetime, timedelta, timezone
import aiohttp
import discord
from discord import app_commands, Interaction
from discord.ui import View, Button
from core.db import get_active_characters
from core.dundam_api import fetch_all_buffers_with_rate_limit


def format_score_korean(num: int) -> str:
    if num >= 100_000_000:
        return f"{num // 100_000_000}억 {num % 100_000_000 // 10_000}만"
    elif num >= 10_000:
        return f"{num // 10_000}만 {num % 10_000}"
    else:
        return f"{num}"


class BufferRankingView(View):
    """버퍼 랭킹 페이지네이션 View"""

    def __init__(self, ranked_characters: list[dict], timestamp: str):
        super().__init__(timeout=300)
        self.ranked_characters = ranked_characters
        self.timestamp = timestamp
        self.current_page = 0
        self.items_per_page = 20
        self.total_pages = (len(ranked_characters) + self.items_per_page - 1) // self.items_per_page

        self.add_item(PreviousButton())
        self.add_item(NextButton())
        self.update_buttons()

    def update_buttons(self):
        for item in self.children:
            if isinstance(item, PreviousButton):
                item.disabled = (self.current_page == 0)
            elif isinstance(item, NextButton):
                item.disabled = (self.current_page >= self.total_pages - 1)

    def get_embed(self) -> discord.Embed:
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.ranked_characters))
        page_characters = self.ranked_characters[start_idx:end_idx]

        embed = discord.Embed(title="버퍼 순위 (버프스코어)", color=discord.Color.green())
        embed.set_footer(text=f"기준 시각: {self.timestamp} | 페이지: {self.current_page + 1}/{self.total_pages}")

        description = ""
        for i, char in enumerate(page_characters, start=start_idx + 1):
            score_kor = format_score_korean(char['buff_score'])
            char_name = char.get('character_name', '알 수 없음')
            adv_name = char.get('adventure_name', '알 수 없음')
            description += f"**{i}위** **{char_name}** ({adv_name})\n"
            description += f"**버프스코어:** {score_kor}\n\n"

        if not description:
            description = "버퍼 랭킹 정보를 가져올 수 있는 캐릭터가 없습니다."

        embed.description = description
        return embed


class PreviousButton(Button):
    def __init__(self):
        super().__init__(
            label="◀ 이전",
            style=discord.ButtonStyle.primary,
            custom_id="buffer_previous_page"
        )

    async def callback(self, interaction: Interaction):
        view: BufferRankingView = self.view
        if view.current_page > 0:
            view.current_page -= 1
            view.update_buttons()
            await interaction.response.edit_message(embed=view.get_embed(), view=view)


class NextButton(Button):
    def __init__(self):
        super().__init__(
            label="다음 ▶",
            style=discord.ButtonStyle.primary,
            custom_id="buffer_next_page"
        )

    async def callback(self, interaction: Interaction):
        view: BufferRankingView = self.view
        if view.current_page < view.total_pages - 1:
            view.current_page += 1
            view.update_buttons()
            await interaction.response.edit_message(embed=view.get_embed(), view=view)


@app_commands.command(name="버퍼순위", description="등록된 캐릭터 중 버퍼의 버프스코어 순위를 조회합니다.")
async def buffer_ranking(interaction: Interaction):
    await interaction.response.defer(thinking=True)

    characters = await get_active_characters()
    if not characters:
        await interaction.followup.send("등록된 캐릭터가 없습니다.")
        return

    async with aiohttp.ClientSession() as session:
        results = await fetch_all_buffers_with_rate_limit(session, characters, limit_per_second=5)

    ranked_characters = sorted([r for r in results if r], key=lambda x: x['buff_score'], reverse=True)

    if not ranked_characters:
        await interaction.followup.send("버퍼 랭킹 정보를 가져올 수 있는 캐릭터가 없습니다.")
        return

    KST = timezone(timedelta(hours=9))
    timestamp = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
    view = BufferRankingView(ranked_characters, timestamp)
    embed = view.get_embed()

    await interaction.followup.send(embed=embed, view=view)
