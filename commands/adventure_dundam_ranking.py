import time
from collections import defaultdict

import discord
from discord import app_commands, Interaction
from discord.ui import View, Button
from core.db import get_active_characters
from core.dnf_api import get_session
from core.dundam_api import fetch_all_with_rate_limit
from core.models import SERVER_MAP


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


class AdventureDundamRankingView(View):
    """모험단 던담 랭킹 페이지네이션 View"""

    def __init__(self, ranked_adventures: list[dict], timestamp: str):
        super().__init__(timeout=300)  # 5분 타임아웃
        self.ranked_adventures = ranked_adventures
        self.timestamp = timestamp
        self.current_page = 0
        self.items_per_page = 20
        self.total_pages = (len(ranked_adventures) + self.items_per_page - 1) // self.items_per_page

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
        end_idx = min(start_idx + self.items_per_page, len(self.ranked_adventures))
        page_adventures = self.ranked_adventures[start_idx:end_idx]

        embed = discord.Embed(title="모험단 던담 데미지 순위", color=discord.Color.purple())
        embed.set_footer(text=f"기준 시각: {self.timestamp} | 페이지: {self.current_page + 1}/{self.total_pages}")

        description = ""
        for i, adv in enumerate(page_adventures, start=start_idx + 1):
            score_kor = format_score_korean(adv['total_damage'])
            char_count = adv['character_count']
            description += f"**{i}위** **{adv['adventure_name']}** ({adv['server_name']})\n"
            description += f"**합산 점수:** {score_kor} (캐릭터 {char_count}개)\n\n"

        if not description:
            description = "모험단 던담 랭킹 정보가 없습니다."

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
        view: AdventureDundamRankingView = self.view
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
        view: AdventureDundamRankingView = self.view
        if view.current_page < view.total_pages - 1:
            view.current_page += 1
            view.update_buttons()
            await interaction.response.edit_message(embed=view.get_embed(), view=view)


def _find_server_id(characters: list[dict], character_name: str) -> str | None:
    """캐릭터 이름으로 서버 ID 조회."""
    char_info = next((c for c in characters if c['character_name'] == character_name), None)
    return char_info['server_id'] if char_info else None


def _aggregate_adventure_damages(
    valid_results: list[dict], characters: list[dict]
) -> dict:
    """모험단별 데미지 합산 딕셔너리 생성."""
    adventure_damages = defaultdict(
        lambda: {'total_damage': 0, 'characters': [], 'server_id': None}
    )
    for result in valid_results:
        adventure_name = result.get('adventure_name', '알 수 없음')
        character_name = result.get('character_name', '알 수 없음')
        entry = adventure_damages[adventure_name]
        entry['total_damage'] += result.get('damage', 0)
        entry['characters'].append(character_name)
        server_id = _find_server_id(characters, character_name)
        entry['server_id'] = entry['server_id'] or server_id
    return adventure_damages


def _build_ranked_list(adventure_damages: dict) -> list[dict]:
    """모험단 합산 데이터를 정렬된 순위 리스트로 변환."""
    ranked_adventures = []
    for adventure_name, data in adventure_damages.items():
        server_name = (
            SERVER_MAP.get(data['server_id'], data['server_id'])
            if data['server_id'] else '알 수 없음'
        )
        ranked_adventures.append({
            'adventure_name': adventure_name,
            'server_name': server_name,
            'total_damage': data['total_damage'],
            'character_count': len(data['characters'])
        })
    ranked_adventures.sort(key=lambda x: x['total_damage'], reverse=True)
    return ranked_adventures


@app_commands.command(name="모험단던담순위", description="모험단별 던담 데미지 합산 순위를 조회합니다.")
async def adventure_dundam_ranking(interaction: Interaction):
    await interaction.response.defer(thinking=True)

    characters = await get_active_characters()
    if not characters:
        await interaction.followup.send("등록된 캐릭터가 없습니다.")
        return

    session = await get_session()
    results = await fetch_all_with_rate_limit(session, characters, limit_per_second=5)

    valid_results = [r for r in results if r]
    if not valid_results:
        await interaction.followup.send("던담 랭킹 정보를 가져올 수 있는 캐릭터가 없습니다.")
        return

    adventure_damages = _aggregate_adventure_damages(valid_results, characters)
    ranked_adventures = _build_ranked_list(adventure_damages)

    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    view = AdventureDundamRankingView(ranked_adventures, timestamp)
    embed = view.get_embed()

    await interaction.followup.send(embed=embed, view=view)
