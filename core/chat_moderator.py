import asyncio
import json
import os
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import aiohttp
from discord import Message, TextChannel
from core.logger import logger


class ChatModerator:
    """
    채널별로 최근 20개 메시지를 큐에 유지하고,
    채널당 1초에 1번씩만(락 기반) API로 큐 전체를 전송해 moderation 결과를 받아 출력한다.

    서버(Lambda)가 기대하는 로그 포맷:
      [HH:MM:SS.mmm] <U|B> <name=...> <msg=...>
    """

    QUEUE_MAXLEN = 20
    TICK_SEC = 1.0

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

    # -----------------------------
    # Helpers: formatting / escaping
    # -----------------------------
    def _format_ts_ms(self, dt: datetime) -> str:
        """HH:MM:SS.mmm (밀리초 3자리)"""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%H:%M:%S.") + dt.strftime("%f")[:3]

    def _escape_for_log(self, s: str) -> str:
        """
        서버 파서가 <...> 태그 기반이라, 본문에 '<', '>'가 들어오면 포맷이 깨질 수 있음.
        줄바꿈은 한 줄=한 메시지 규칙을 지키기 위해 \n 문자열로 치환.
        """
        return (s or "").replace("<", "＜").replace(">", "＞").replace("\n", "\\n").replace("\r", "")

    def _format_line(self, who: str, name: str, msg: str, created_at: datetime) -> str:
        """
        who: 'U' or 'B'
        """
        return (
            f"[{self._format_ts_ms(created_at)}] "
            f"<{who}> <name={self._escape_for_log(name)}> "
            f"<msg={self._escape_for_log(msg)}>"
        )

    # -----------------------------
    # Channel init
    # -----------------------------
    def _ensure_channel(self, channel_id: int):
        if channel_id not in self.message_queues:
            self.message_queues[channel_id] = deque(maxlen=self.QUEUE_MAXLEN)
        if channel_id not in self.channel_events:
            self.channel_events[channel_id] = asyncio.Event()
        if channel_id not in self.channel_tasks:
            self.channel_tasks[channel_id] = asyncio.create_task(self._channel_worker(channel_id))

    # -----------------------------
    # Public entry: message handler
    # -----------------------------
    async def handle_message(self, message: Message):
        channel_id = message.channel.id
        self._ensure_channel(channel_id)

        # worker가 send할 수 있도록 채널 캐시
        if isinstance(message.channel, TextChannel):
            self.channel_cache[channel_id] = message.channel
        else:
            return

        # 유저 메시지 큐 적재 (서버 포맷과 동일)
        line = self._format_line(
            who="U",
            name=message.author.display_name,
            msg=message.content or "",
            created_at=message.created_at,
        )
        self.message_queues[channel_id].append(line)

        # 처리 필요 이벤트 세팅
        self.channel_events[channel_id].set()

        logger.info(
            f"채널({channel_id}) 큐 상태: size={len(self.message_queues[channel_id])}, "
            f"event={self.channel_events[channel_id].is_set()}, "
            f"locked={self.channel_locks[channel_id].locked()}"
        )

    # -----------------------------
    # Worker: 1초에 1번 처리
    # -----------------------------
    async def _channel_worker(self, channel_id: int):
        while True:
            await asyncio.sleep(self.TICK_SEC)

            event = self.channel_events.get(channel_id)
            if event is None or not event.is_set():
                continue

            channel = self.channel_cache.get(channel_id)
            if channel is None:
                continue

            lock = self.channel_locks[channel_id]
            if lock.locked():
                # 이미 API 호출 중이면 이번 tick은 스킵
                continue

            async with lock:
                # 락 안에서 clear해야, API 호출 중 들어온 메시지는 다음 tick에서 처리됨
                event.clear()
                await self._moderate_channel(channel)

    # -----------------------------
    # Core: send queue to API
    # -----------------------------
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

            # ✅ 서버가 route=NONE이면 클라이언트는 무조건 출력 금지 (최종 안전장치)
            route = (response.get("route") or "").strip().upper()
            if route == "NONE":
                return

            msg = (response.get("message") or "").strip()
            if not msg:
                return

            bot_message = await channel.send(msg)

            # 봇 메시지를 큐에 추가 (서버 포맷과 동일하게 <B>)
            bot_line = self._format_line(
                who="B",
                name=bot_message.author.display_name,
                msg=bot_message.content or "",
                created_at=bot_message.created_at,
            )
            self.message_queues[channel_id].append(bot_line)

            logger.info(
                f"채널({channel_id}) 봇 메시지 전송 + 큐 추가 완료. "
                f"queue_size={len(self.message_queues[channel_id])}"
            )

        except Exception as e:
            logger.exception(f"Error during moderation(channel={channel_id}): {e}")

    # -----------------------------
    # HTTP
    # -----------------------------
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

    # -----------------------------
    # Response normalize / parse safety
    # -----------------------------
    def _normalize_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        has_expected_keys = (
            "message" in data or "riskLevel" in data
            or "summary" in data or "route" in data
        )
        if isinstance(data, dict) and has_expected_keys:
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
