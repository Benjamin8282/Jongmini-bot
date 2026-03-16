# core/dundam_queue.py
import asyncio
import os
import time
from datetime import datetime, timezone, timedelta

from core.db import get_dundam_daily_usage, increment_dundam_daily_usage
from core.logger import logger

KST = timezone(timedelta(hours=9))


class DundamQueueManager:
    """던담 API 공유 큐 매니저 — rate limit + 일일 한도 + FIFO 큐"""

    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._rate_semaphore = asyncio.Semaphore(5)
        self._daily_limit = int(os.getenv("DUNDAM_DAILY_LIMIT", "20000"))
        self._worker_task: asyncio.Task | None = None
        self._current_job: dict | None = None
        self._last_call_time = 0.0
        self._min_interval = 0.2  # 초당 5회 = 0.2초 간격
        logger.info(f"DundamQueueManager 생성: 일일 한도={self._daily_limit}")

    async def start(self):
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())
            logger.info("던담 큐 워커 시작됨")

    async def _execute_job(self, job: dict):
        """단일 작업 실행 및 결과/예외 전달."""
        self._current_job = job
        logger.info(f"큐 작업 시작: {job['job_type']} (요청자: {job.get('requester', 'system')})")
        try:
            result = await job['coro_factory']()
            job['future'].set_result(result)
        except Exception as e:
            logger.error(f"큐 작업 실패: {job['job_type']} - {e}")
            if not job['future'].done():
                job['future'].set_exception(e)
        finally:
            self._current_job = None
            self._queue.task_done()

    async def _worker(self):
        while True:
            try:
                job = await self._queue.get()
                await self._execute_job(job)
            except asyncio.CancelledError:
                logger.info("던담 큐 워커 종료됨")
                break
            except Exception as e:
                logger.error(f"던담 큐 워커 예외: {e}")

    async def submit(self, job_type: str, coro_factory, requester: str = "system",
                     estimated_calls: int = 0) -> asyncio.Future:
        """작업을 큐에 제출. 반환된 Future를 await하면 결과를 받을 수 있음."""
        future = asyncio.get_event_loop().create_future()
        job = {
            'job_type': job_type,
            'coro_factory': coro_factory,
            'future': future,
            'requester': requester,
            'estimated_calls': estimated_calls,
            'submitted_at': time.time(),
        }
        await self._queue.put(job)
        logger.info(f"큐에 작업 추가: {job_type} (대기 수: {self._queue.qsize()})")
        return future

    async def rate_limited_post(self, session, url, params=None):
        """rate limit 적용된 단일 POST 호출"""
        async with self._rate_semaphore:
            # 최소 간격 보장
            now = time.time()
            elapsed = now - self._last_call_time
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_call_time = time.time()

            # 일일 사용량 증가
            today = datetime.now(KST).strftime('%Y-%m-%d')
            await increment_dundam_daily_usage(today, 1)

            async with session.post(url, params=params) as response:
                if response.status == 200:
                    return await response.json(content_type=None)
                elif response.status in (403, 429):
                    logger.warning(f"던담 API {response.status}: rate limit 대기")
                    await asyncio.sleep(2)
                    return None
                else:
                    logger.error(f"던담 API HTTP {response.status}")
                    return None

    async def rate_limited_get(self, session, url):
        """rate limit 적용된 단일 GET 호출"""
        async with self._rate_semaphore:
            now = time.time()
            elapsed = now - self._last_call_time
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_call_time = time.time()

            today = datetime.now(KST).strftime('%Y-%m-%d')
            await increment_dundam_daily_usage(today, 1)

            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json(content_type=None)
                elif response.status in (403, 429):
                    logger.warning(f"던담 API {response.status}: rate limit 대기")
                    await asyncio.sleep(2)
                    return None
                else:
                    logger.error(f"던담 API HTTP {response.status}")
                    return None

    async def check_daily_limit(self, required_calls: int = 0) -> tuple[bool, int]:
        """일일 한도 확인. (충분한지, 남은 횟수) 반환"""
        today = datetime.now(KST).strftime('%Y-%m-%d')
        used = await get_dundam_daily_usage(today)
        remaining = max(0, self._daily_limit - used)
        sufficient = remaining >= required_calls
        return sufficient, remaining

    def get_queue_info(self) -> dict:
        """큐 상태 정보 반환"""
        queue_size = self._queue.qsize()

        return {
            'current_job': self._current_job,
            'queue_size': queue_size,
            'is_busy': self._current_job is not None,
        }

    def estimate_wait_time(self, estimated_calls: int) -> float:
        """대기 시간 예측 (초). 현재 작업 + 큐 대기 + 본인 작업"""
        info = self.get_queue_info()
        wait = 0.0

        # 현재 진행 중인 작업의 남은 시간 (추정)
        if info['current_job']:
            remaining = info['current_job'].get('estimated_calls', 0)
            wait += remaining * self._min_interval

        # 큐에 대기 중인 작업들 (정확한 추정은 어렵지만 평균으로)
        wait += info['queue_size'] * 60  # 큐 작업당 평균 1분 가정

        # 본인 작업
        wait += estimated_calls * self._min_interval

        return wait
