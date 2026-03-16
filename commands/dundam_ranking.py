from datetime import datetime, timedelta, timezone
import aiohttp
import discord
from discord import app_commands, Interaction
from discord.ui import View, Button
from core.db import (
    get_active_characters,
    save_dundam_ranking_cache, get_dundam_ranking_cache, get_dundam_ranking_cache_timestamp,
)
from core.dundam_api import fetch_all_with_rate_limit, fetch_all_buffers_with_rate_limit
from core.logger import logger

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
    db_mode = 'dealer' if mode == '딜러' else 'buffer'
    config = MODE_CONFIG[mode]
    score_key = config['score_key']

    # 캐시 우선 조회
    cached = await get_dundam_ranking_cache(db_mode)
    cached_ts = await get_dundam_ranking_cache_timestamp(db_mode)

    # API에서 실시간 갱신 시도
    characters = await get_active_characters()
    ranked = None

    if characters:
        try:
            async with aiohttp.ClientSession() as session:
                if mode == "딜러":
                    results = await fetch_all_with_rate_limit(session, characters, limit_per_second=5)
                    ranked = sorted([r for r in results if r], key=lambda x: x['damage'], reverse=True)
                else:
                    results = await fetch_all_buffers_with_rate_limit(session, characters, limit_per_second=5)
                    ranked = sorted([r for r in results if r], key=lambda x: x['buff_score'], reverse=True)

            # 캐시에 저장
            if ranked:
                now_str = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
                cache_entries = []
                for r in ranked:
                    cache_entries.append({
                        'character_id': r.get('character_id', ''),
                        'server_id': r.get('server_id', ''),
                        'mode': db_mode,
                        'character_name': r.get('character_name', ''),
                        'adventure_name': r.get('adventure_name', ''),
                        'score': r.get(score_key, 0),
                        'updated_at': now_str,
                    })
                await save_dundam_ranking_cache(cache_entries)
                logger.info(f"던담순위 캐시 갱신 완료: {db_mode} {len(cache_entries)}건")
        except Exception as e:
            logger.warning(f"던담순위 실시간 조회 실패, 캐시 사용: {e}")
            ranked = None

    # 실시간 실패 시 캐시 사용
    if not ranked and cached:
        ranked = [{
            'character_name': c['character_name'],
            'adventure_name': c['adventure_name'],
            score_key: c['score'],
        } for c in cached]
        timestamp = f"{cached_ts} (캐시)"
    elif ranked:
        timestamp = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
    else:
        if not characters:
            await interaction.followup.send("등록된 캐릭터가 없습니다.")
        else:
            await interaction.followup.send(config["empty_msg"])
        return

    view = DundamRankingView(ranked, timestamp, mode)
    embed = view.get_embed()
    await interaction.followup.send(embed=embed, view=view)
