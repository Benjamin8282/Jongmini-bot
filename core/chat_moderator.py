import asyncio
import json
import os
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import aiohttp
from discord import Message, TextChannel
from core.logger import logger


class ChatModerator:
    def __init__(self):
        self.ENDPOINT = os.getenv("MODERATE_ENDPOINT")
        self.API_KEY = os.getenv("MODERATE_API_KEY")
        self.KEY_NAME = os.getenv("MODERATE_KEY_NAME")

        if not all([self.ENDPOINT, self.API_KEY, self.KEY_NAME]):
            raise ValueError("MODERATE_ENDPOINT, MODERATE_API_KEY, MODERATE_KEY_NAME 환경 변수를 설정해야 합니다.")

        self.message_queues: Dict[int, deque] = {}
        self.last_api_call_time: Dict[int, datetime] = {}
        self.short_term_message_counts: Dict[int, List[datetime]] = {}

    async def handle_message(self, message: Message):
        channel_id = message.channel.id
        if channel_id not in self.message_queues:
            self.message_queues[channel_id] = deque(maxlen=30)
            self.short_term_message_counts[channel_id] = []

        # [HH:MM] 이름: 내용 형식으로 변환
        formatted_message = (
            f"<{message.id}> [{message.created_at.strftime('%H:%M')}] "
            f"{message.author.display_name}: {message.content}"
        )
        self.message_queues[channel_id].append((message.id, formatted_message))
        self.short_term_message_counts[channel_id].append(message.created_at)

        logger.info(f"채널({channel_id}) 큐 상태: 크기={len(self.message_queues[channel_id])}, 단기 카운트={len(self.short_term_message_counts[channel_id])}")

        if await self._should_call_api(channel_id):
            self.last_api_call_time[channel_id] = datetime.now(timezone.utc) # timezone.utc 추가
            self.short_term_message_counts[channel_id] = []
            await self._moderate_channel(message.channel)

    async def _should_call_api(self, channel_id: int) -> bool:
        # 조건 1: 새로운 채팅 10개
        if len(self.message_queues[channel_id]) >= 10:
            last_call = self.last_api_call_time.get(channel_id)
            if not last_call or (datetime.now(timezone.utc) - last_call).total_seconds() > 10:
                # 마지막 호출 후 10개가 쌓였는지 확인하기 위해, 큐가 꽉 찼을 때만 호출
                if len(self.message_queues[channel_id]) == self.message_queues[channel_id].maxlen:
                     return True
                # 처음 10개 도달
                if len(self.message_queues[channel_id]) == 10 and not last_call:
                    return True


        # 조건 2: 10초 이내 5회 이상
        now = datetime.now(timezone.utc)
        ten_seconds_ago = now - timedelta(seconds=10)
        recent_messages = [
            t for t in self.short_term_message_counts.get(channel_id, []) if t > ten_seconds_ago
        ]
        self.short_term_message_counts[channel_id] = recent_messages  # 오래된 메시지 정리
        if len(recent_messages) >= 5:
            return True

        return False

    async def _moderate_channel(self, channel: TextChannel):
        channel_id = channel.id
        chat_log = "\n".join([msg for _, msg in self.message_queues[channel_id]])
        
        try:
            response = await self._send_to_api(chat_log) # asyncio.to_thread 제거
            if not response:
                return

            if response.get("message"):
                await channel.send(response["message"])

            if response.get("deleteMessageIds"):
                # 현재 큐에 있는 메시지 중에서만 삭제 시도
                all_message_ids_in_queue = {msg_id for msg_id, _ in self.message_queues[channel_id]}
                messages_to_delete_ids = [
                    msg_id for msg_id in response["deleteMessageIds"] if msg_id in all_message_ids_in_queue
                ]
                
                # discord.py 는 int 리스트로 id를 받아 메시지를 삭제하는 기능이 없음
                # bulk delete는 100개 제한, 14일 지난 메시지 삭제 불가 등의 제약이 있음
                # 개별 메시지를 삭제하는 것으로 구현
                for msg_id in messages_to_delete_ids:
                    try:
                        msg_to_delete = await channel.fetch_message(msg_id)
                        await msg_to_delete.delete()
                    except Exception as e:
                        print(f"Failed to delete message {msg_id}: {e}")

        except Exception as e:
            print(f"Error during moderation: {e}")

    async def _send_to_api(self, chat_log: str) -> Dict[str, Any]: # async def로 변경
        payload = {"chat_log": chat_log}
        headers = {self.KEY_NAME: self.API_KEY, "Accept": "application/json"}
        timeout = aiohttp.ClientTimeout(total=20, connect=5) # aiohttp.ClientTimeout 사용

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session: # aiohttp.ClientSession 사용
                async with session.post(self.ENDPOINT, headers=headers, json=payload) as response:
                    if response.status != 200:
                        print(f"HTTP {response.status}: {await response.text()}")
                        return {}
                    
                    data = await response.json()
                    normalized = self._normalize_response(data)
                    print("Moderation API response:", self._pretty(normalized))
                    return normalized

        except aiohttp.ClientError as e: # aiohttp.ClientError 예외 처리
            print(f"ERROR: aiohttp request failed: {e}")
        except json.JSONDecodeError as e: # json.JSONDecodeError 예외 처리
            print(f"ERROR: invalid json response: {e}")
        return {}

    def _normalize_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if "riskLevel" in data and "summary" in data:
            return data
        if "result" in data and isinstance(data["result"], str):
            try:
                return json.loads(data["result"])
            except json.JSONDecodeError:
                return {"raw": data["result"]}
        if "raw" in data:
            return data
        return {"_unknown_format": data}

    def _pretty(self, obj: Any) -> str:
        return json.dumps(obj, ensure_ascii=False, indent=2)
