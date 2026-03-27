import asyncio
import traceback
from datetime import datetime, timedelta, timezone

import discord

from core import dnf_api
from core.db import (
    get_all_characters_grouped_by_adventure,
    get_mist_assimilation,
    upsert_mist_assimilation,
    get_output_channel,
)
from core.logger import logger
from core.models import SERVER_MAP, MAX_MIST_LEVEL

POLL_INTERVAL = 30  # 30초
KST = timezone(timedelta(hours=9))


def _build_level_up_embed(adventure_name: str, server_id: str,
                          old_level: int, new_level: int,
                          exp_rate: str) -> discord.Embed:
    server_name = SERVER_MAP.get(server_id, server_id)
    embed = discord.Embed(
        title="🌫️ 안개융화 레벨 업!",
        description=(
            f"**{adventure_name}** ({server_name}) 모험단의 "
            f"안개융화 레벨이 **{old_level} → {new_level}**(으)로 상승했습니다!\n"
            f"경험치: {exp_rate}"
        ),
        color=0x7B68EE,
    )
    return embed


async def _resolve_item_channel(bot, guild_id) -> discord.TextChannel | None:
    channel_id = await get_output_channel(guild_id, 'item')
    if not channel_id:
        return None
    return bot.get_channel(int(channel_id))


async def _poll_adventure_mist(bot, guild_id, characters, semaphore):
    """단일 모험단의 안개융화 폴링"""
    async with semaphore:
        char = characters[0]
        server_id = char['server_id']
        character_id = char['character_id']
        adventure_name = char['adventure_name']

        mist_data = await dnf_api.fetch_mist_assimilation(server_id, character_id)
        if mist_data is None:
            return

        new_level = mist_data.get("level", 0)
        exp_rate = mist_data.get("expRate", "0%")

        existing = await get_mist_assimilation(adventure_name, server_id)

        if existing is None:
            max_reached = datetime.now(KST).isoformat() if new_level >= MAX_MIST_LEVEL else None
            await upsert_mist_assimilation(
                adventure_name, server_id, character_id, new_level, exp_rate, max_reached
            )
            logger.info(f"[안개융화] 초기 등록: {adventure_name} Lv.{new_level} ({exp_rate})")
            return

        old_level = existing['level']

        if new_level > old_level:
            channel = await _resolve_item_channel(bot, guild_id)
            if channel:
                embed = _build_level_up_embed(
                    adventure_name, server_id, old_level, new_level, exp_rate
                )
                await channel.send(embed=embed)
                logger.info(f"[안개융화] 레벨업 알림: {adventure_name} {old_level} → {new_level}")

        if new_level != old_level or exp_rate != existing['exp_rate']:
            max_reached = existing.get('max_reached_at')
            if new_level >= MAX_MIST_LEVEL and not max_reached:
                max_reached = datetime.now(KST).isoformat()
            await upsert_mist_assimilation(
                adventure_name, server_id, character_id,
                new_level, exp_rate, max_reached
            )


async def poll_all_mist(bot, guild_id):
    grouped = await get_all_characters_grouped_by_adventure()
    if not grouped:
        return

    semaphore = asyncio.Semaphore(10)
    tasks = [
        _poll_adventure_mist(bot, guild_id, chars, semaphore)
        for chars in grouped.values()
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            logger.warning(f"[안개융화] 폴링 오류: {r}")


async def periodic_poll_mist(bot, guild_id):
    while True:
        try:
            await poll_all_mist(bot, guild_id)
        except Exception as e:
            logger.error(f"[안개융화] 폴링 루프 오류: {e}")
            logger.error(traceback.format_exc())
        finally:
            await asyncio.sleep(POLL_INTERVAL)
