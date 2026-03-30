from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands, Interaction
from discord.ui import View, Button
from core.db import (
    get_active_characters,
    save_dundam_ranking_cache, get_dundam_ranking_cache, get_dundam_ranking_cache_timestamp,
)
from core.dnf_api import get_session
from core.dundam_api import fetch_all_with_rate_limit, fetch_all_buffers_with_rate_limit
from core.logger import logger
from core.models import format_score_korean

KST = timezone(timedelta(hours=9))


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

_FETCH_DISPATCHERS = {
    "딜러": lambda session, chars: fetch_all_with_rate_limit(session, chars, limit_per_second=5),
    "버퍼": lambda session, chars: fetch_all_buffers_with_rate_limit(session, chars, limit_per_second=5),
}

_SORT_KEYS = {
    "딜러": "damage",
    "버퍼": "buff_score",
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


async def _fetch_ranked(mode: str, characters: list[dict], score_key: str) -> list[dict] | None:
    """API에서 랭킹 데이터를 가져와 정렬. 실패 시 None."""
    sort_key = _SORT_KEYS[mode]
    try:
        session = await get_session()
        fetcher = _FETCH_DISPATCHERS[mode]
        results = await fetcher(session, characters)
        ranked = sorted(
            [r for r in results if r],
            key=lambda x: x[sort_key], reverse=True
        )
        return ranked if ranked else None
    except Exception as e:
        logger.warning(f"던담순위 실시간 조회 실패, 캐시 사용: {e}")
        return None


async def _save_to_cache(ranked: list[dict], db_mode: str, score_key: str):
    """랭킹 결과를 캐시에 저장."""
    now_str = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
    cache_entries = [
        {
            'character_id': r.get('character_id', ''),
            'server_id': r.get('server_id', ''),
            'mode': db_mode,
            'character_name': r.get('character_name', ''),
            'adventure_name': r.get('adventure_name', ''),
            'score': r.get(score_key, 0),
            'updated_at': now_str,
        }
        for r in ranked
    ]
    await save_dundam_ranking_cache(cache_entries)
    logger.info(f"던담순위 캐시 갱신 완료: {db_mode} {len(cache_entries)}건")


def _ranked_from_cache(cached: list[dict], score_key: str) -> list[dict]:
    """캐시 데이터를 ranked 리스트 형태로 변환."""
    return [{
        'character_name': c['character_name'],
        'adventure_name': c['adventure_name'],
        score_key: c['score'],
    } for c in cached]


async def _resolve_ranked(
    mode: str, db_mode: str, score_key: str, characters: list[dict], cached: list[dict], cached_ts: str
) -> tuple[list[dict], str] | None:
    """실시간 조회 또는 캐시에서 랭킹 데이터 resolve. 실패 시 None."""
    ranked = await _fetch_ranked(mode, characters, score_key) if characters else None
    if ranked:
        await _save_to_cache(ranked, db_mode, score_key)
        return ranked, datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
    if cached:
        return _ranked_from_cache(cached, score_key), f"{cached_ts} (캐시)"
    return None


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

    characters = await get_active_characters()
    cached = await get_dundam_ranking_cache(db_mode)
    cached_ts = await get_dundam_ranking_cache_timestamp(db_mode)

    resolved = await _resolve_ranked(mode, db_mode, config['score_key'], characters, cached, cached_ts)
    if not resolved:
        msg = "등록된 캐릭터가 없습니다." if not characters else config["empty_msg"]
        await interaction.followup.send(msg)
        return

    ranked, timestamp = resolved
    view = DundamRankingView(ranked, timestamp, mode)
    await interaction.followup.send(embed=view.get_embed(), view=view)
