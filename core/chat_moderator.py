import json
import os
import asyncio
from collections import deque, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import aiohttp
from discord import Message, TextChannel
from core.logger import logger


class ChatModerator:
    BOT_TAG = "[BOT]"  # ✅ 모델이 무시할 봇 메시지 태그

    def __init__(self):
        self.ENDPOINT = os.getenv("MODERATE_ENDPOINT")
        self.API_KEY = os.getenv("MODERATE_API_KEY")
        self.KEY_NAME = os.getenv("MODERATE_KEY_NAME")

        if not all([self.ENDPOINT, self.API_KEY, self.KEY_NAME]):
            raise ValueError("MODERATE_ENDPOINT, MODERATE_API_KEY, MODERATE_KEY_NAME 환경 변수를 설정해야 합니다.")

        # 채널별 최근 로그 큐 (최대 20개) - 문자열만 저장
        self.message_queues: Dict[int, deque[str]] = {}

        # 채널별 "처리 필요" 이벤트
        self.channel_events: Dict[int, asyncio.Event] = {}

        # 채널별 worker task
        self.channel_tasks: Dict[int, asyncio.Task] = {}

        # 채널별 API 요청 동시성 방지 lock
        self.channel_locks = defaultdict(asyncio.Lock)

        # 채널 객체 캐시 (worker가 send 가능하도록)
        self.channel_cache: Dict[int, TextChannel] = {}

    def _format_ts_ms(self, dt: datetime) -> str:
        """[HH:MM:SS.mmm] 밀리초(3자리)까지"""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%H:%M:%S.") + dt.strftime("%f")[:3]

    def _ensure_channel(self, channel_id: int):
        if channel_id not in self.message_queues:
            self.message_queues[channel_id] = deque(maxlen=20)
        if channel_id not in self.channel_events:
            self.channel_events[channel_id] = asyncio.Event()
        if channel_id not in self.channel_tasks:
            self.channel_tasks[channel_id] = asyncio.create_task(self._channel_worker(channel_id))

    async def handle_message(self, message: Message):
        channel_id = message.channel.id
        self._ensure_channel(channel_id)

        if isinstance(message.channel, TextChannel):
            self.channel_cache[channel_id] = message.channel

        # 유저 메시지 (id 제거, ms 포함)
        formatted = (
            f"[{self._format_ts_ms(message.created_at)}] "
            f"{message.author.display_name}: {message.content}"
        )
        self.message_queues[channel_id].append(formatted)

        self.channel_events[channel_id].set()

        logger.info(
            f"채널({channel_id}) 큐 상태: 크기={len(self.message_queues[channel_id])}, "
            f"event={self.channel_events[channel_id].is_set()}, "
            f"locked={self.channel_locks[channel_id].locked()}"
        )

    async def _channel_worker(self, channel_id: int):
        """채널별 1초에 1번만 처리 (락 중이면 스킵)"""
        while True:
            await asyncio.sleep(1)

            event = self.channel_events.get(channel_id)
            if event is None or not event.is_set():
                continue

            lock = self.channel_locks[channel_id]
            if lock.locked():
                continue

            channel = self.channel_cache.get(channel_id)
            if channel is None:
                continue

            event.clear()

            async with lock:
                await self._moderate_channel(channel)

    async def _moderate_channel(self, channel: TextChannel):
        channel_id = channel.id
        self._ensure_channel(channel_id)

        if not self.message_queues[channel_id]:
            return

        chat_log = "\n".join(self.message_queues[channel_id])

        try:
            response = await self._send_to_api(chat_log)
            if not response:
                return

            msg = (response.get("message") or "").strip()
            if not msg:
                return

            bot_message = await channel.send(msg)

            # ✅ 봇 메시지를 큐에 추가하되 BOT_TAG 붙여서 모델이 무시하게 함
            bot_formatted = (
                f"[{self._format_ts_ms(bot_message.created_at)}] "
                f"{self.BOT_TAG} {bot_message.author.display_name}: {bot_message.content}"
            )
            self.message_queues[channel_id].append(bot_formatted)

            logger.info(
                f"채널({channel_id}) 봇 메시지 전송 + 큐 추가(BOT_TAG) 완료. "
                f"큐 크기={len(self.message_queues[channel_id])}"
            )

        except Exception as e:
            logger.exception(f"Error during moderation(channel={channel_id}): {e}")

    async def _send_to_api(self, chat_log: str) -> Dict[str, Any]:
        payload = {"chat_log": chat_log}
        headers = {self.KEY_NAME: self.API_KEY, "Accept": "application/json"}
        timeout = aiohttp.ClientTimeout(total=20, connect=5)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.ENDPOINT, headers=headers, json=payload) as response:
                    if response.status != 200:
                        logger.warning(f"HTTP {response.status}: {await response.text()}")
                        return {}

                    data = await response.json()
                    normalized = self._normalize_response(data)
                    logger.info("Moderation API response:\n" + self._pretty(normalized))
                    return normalized

        except aiohttp.ClientError as e:
            logger.warning(f"ERROR: aiohttp request failed: {e}")
        except json.JSONDecodeError as e:
            logger.warning(f"ERROR: invalid json response: {e}")
        return {}

    def _normalize_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(data, dict) and ("message" in data or "riskLevel" in data or "summary" in data):
            return data

        text_to_parse: Optional[str] = None
        if isinstance(data, dict):
            if "result" in data and isinstance(data["result"], str):
                text_to_parse = data["result"].strip()
            elif "raw" in data and isinstance(data["raw"], str):
                text_to_parse = data["raw"].strip()

        if text_to_parse:
            return self._parse_model_json(text_to_parse)

        return {"_unknown_format": data}

    def _pretty(self, obj: Any) -> str:
        return json.dumps(obj, ensure_ascii=False, indent=2)

    def _strip_control_chars(self, s: str) -> str:
        if not isinstance(s, str):
            return ""
        return "".join(ch for ch in s if ch in ("\t", "\n", "\r") or ord(ch) >= 0x20)

    def _extract_json_object(self, s: str) -> str:
        if not isinstance(s, str):
            return ""
        start = s.find("{")
        end = s.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return s.strip()
        return s[start:end + 1].strip()

    def _parse_model_json(self, raw_text: str) -> Dict[str, Any]:
        if raw_text is None:
            return {"raw": "", "_note": "empty"}

        s = raw_text
        if not isinstance(s, str):
            if isinstance(s, dict):
                return s
            return {"raw": str(s), "_note": "non_string"}

        s = self._strip_control_chars(s).strip()
        if not s:
            return {"raw": "", "_note": "empty"}

        if s.startswith('"') and s.endswith('"'):
            try:
                s = json.loads(s)
                if isinstance(s, str):
                    s = self._strip_control_chars(s).strip()
            except Exception:
                pass

        candidate = self._extract_json_object(s)

        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
            return {"raw": candidate, "_note": "parsed but not a dict"}
        except json.JSONDecodeError:
            pass

        last = candidate.rfind("}")
        if last != -1:
            candidate2 = candidate[: last + 1].strip()
            try:
                parsed2 = json.loads(candidate2)
                if isinstance(parsed2, dict):
                    return parsed2
                return {"raw": candidate2, "_note": "parsed but not a dict"}
            except Exception as e2:
                return {"raw": candidate2, "_note": f"json_decode_error:{str(e2)}"}

        return {"raw": candidate, "_note": "invalid or incomplete json"}
