from datetime import datetime, timedelta, timezone
import aiohttp
import discord
from discord import app_commands, Interaction
from discord.ui import View, Button
from core.db import get_active_characters
from core.dundam_api import fetch_all_with_rate_limit, fetch_all_buffers_with_rate_limit

KST = timezone(timedelta(hours=9))


def format_score_korean(num: int) -> str:
    if num >= 100_000_000:
        억 = num // 100_000_000
        만 = (num % 100_000_000) // 10_000
        if 만 > 0:
            return f"{억}억 {만}만"
        return f"{억}억"
    elif num >= 10_000:
        만 = num // 10_000
        나머지 = num % 10_000
        if 나머지 > 0:
            return f"{만}만 {나머지}"
        return f"{만}만"
    else:
        return f"{num}"


# 딜러/버퍼 모드별 설정
MODE_CONFIG = {
    "딜러": {
        "title": "던담 딜러 순위",
        "color": discord.Color.gold(),
        "score_key": "damage",
        "score_label": "점수",
        "empty_msg": "딜러 랭킹 정보를 가져올 수 있는 캐릭터가 없습니다.",
    },
    "버퍼": {
        "title": "던담 버퍼 순위 (버프스코어)",
        "color": discord.Color.green(),
        "score_key": "buff_score",
        "score_label": "버프스코어",
        "empty_msg": "버퍼 랭킹 정보를 가져올 수 있는 캐릭터가 없습니다.",
    },
}


class DundamRankingView(View):
    """던담 랭킹 페이지네이션 View (딜러/버퍼 공용)"""

    def __init__(self, ranked_characters: list[dict], timestamp: str, mode: str):
        super().__init__(timeout=300)
        self.ranked_characters = ranked_characters
        self.timestamp = timestamp
        self.mode = mode
        self.config = MODE_CONFIG[mode]
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

        embed = discord.Embed(title=self.config["title"], color=self.config["color"])
        embed.set_footer(text=f"기준 시각: {self.timestamp} | 페이지: {self.current_page + 1}/{self.total_pages}")

        score_key = self.config["score_key"]
        score_label = self.config["score_label"]

        description = ""
        for i, char in enumerate(page_characters, start=start_idx + 1):
            score_kor = format_score_korean(char[score_key])
            char_name = char.get('character_name', '알 수 없음')
            adv_name = char.get('adventure_name', '알 수 없음')
            description += f"**{i}위** **{char_name}** ({adv_name})\n"
            description += f"**{score_label}:** {score_kor}\n\n"

        if not description:
            description = self.config["empty_msg"]

        embed.description = description
        return embed


class PreviousButton(Button):
    def __init__(self):
        super().__init__(
            label="◀ 이전",
            style=discord.ButtonStyle.primary,
            custom_id="dundam_previous_page"
        )

    async def callback(self, interaction: Interaction):
        view: DundamRankingView = self.view
        if view.current_page > 0:
            view.current_page -= 1
            view.update_buttons()
            await interaction.response.edit_message(embed=view.get_embed(), view=view)


class NextButton(Button):
    def __init__(self):
        super().__init__(
            label="다음 ▶",
            style=discord.ButtonStyle.primary,
            custom_id="dundam_next_page"
        )

    async def callback(self, interaction: Interaction):
        view: DundamRankingView = self.view
        if view.current_page < view.total_pages - 1:
            view.current_page += 1
            view.update_buttons()
            await interaction.response.edit_message(embed=view.get_embed(), view=view)


@app_commands.command(name="던담순위", description="등록된 캐릭터의 던담 딜러/버퍼 순위를 조회합니다.")
@app_commands.describe(유형="딜러 또는 버퍼 순위를 선택하세요")
@app_commands.choices(유형=[
    app_commands.Choice(name="딜러", value="딜러"),
    app_commands.Choice(name="버퍼", value="버퍼"),
])
async def dundam_ranking(interaction: Interaction, 유형: app_commands.Choice[str]):
    await interaction.response.defer(thinking=True)
    mode = 유형.value

    characters = await get_active_characters()
    if not characters:
        await interaction.followup.send("등록된 캐릭터가 없습니다.")
        return

    async with aiohttp.ClientSession() as session:
        if mode == "딜러":
            results = await fetch_all_with_rate_limit(session, characters, limit_per_second=5)
            ranked = sorted([r for r in results if r], key=lambda x: x['damage'], reverse=True)
        else:
            results = await fetch_all_buffers_with_rate_limit(session, characters, limit_per_second=5)
            ranked = sorted([r for r in results if r], key=lambda x: x['buff_score'], reverse=True)

    config = MODE_CONFIG[mode]
    if not ranked:
        await interaction.followup.send(config["empty_msg"])
        return

    timestamp = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
    view = DundamRankingView(ranked, timestamp, mode)
    embed = view.get_embed()

    await interaction.followup.send(embed=embed, view=view)
