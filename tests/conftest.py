"""공통 테스트 fixture."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pandas as pd
import pytest
from dotenv import load_dotenv

# .env 파일에서 API 키 등 환경변수 로드
load_dotenv()

KST = timezone(timedelta(hours=9))

# ─── 이벤트 루프 ───

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ─── 테스트 DB ───

TEST_DB_PATH = Path("data/test_characters.db")


@pytest.fixture
async def test_db(tmp_path):
    """임시 SQLite DB 생성 및 초기화."""
    db_path = tmp_path / "test.db"

    # core.db 모듈의 DB_PATH를 임시 경로로 교체
    import core.db as db_module
    original_path = db_module.DB_PATH
    db_module.DB_PATH = db_path

    await db_module.init_db()
    yield db_path

    db_module.DB_PATH = original_path


# ─── 샘플 데이터 ───

@pytest.fixture
def sample_price_records():
    """시세 테스트용 가격 기록 리스트."""
    now = datetime.now(KST)
    records = []
    base_price = 10000
    for i in range(100):
        dt = now - timedelta(hours=100 - i)
        # 가격 변동 시뮬레이션
        price = base_price + (i * 50) + ((-1) ** i * 200)
        records.append({
            "sold_date": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "unit_price": price,
            "price": price * 1,
            "count": max(1, i % 5),
        })
    return records


@pytest.fixture
def sample_ohlc_df():
    """테스트용 OHLC DataFrame (30캔들)."""
    dates = pd.date_range("2025-01-01", periods=30, freq="1h")
    base = 10000
    data = []
    for i in range(30):
        o = base + i * 100
        h = o + 300
        low = o - 100
        c = o + 150
        v = 10 + i
        data.append({"open": o, "high": h, "low": low, "close": c, "volume": v})
    df = pd.DataFrame(data, index=dates)
    return df


@pytest.fixture
def sample_ohlc_bearish():
    """하락 추세 OHLC DataFrame."""
    dates = pd.date_range("2025-01-01", periods=30, freq="1h")
    base = 20000
    data = []
    for i in range(30):
        o = base - i * 100
        h = o + 50
        low = o - 200
        c = o - 80
        v = 10 + i
        data.append({"open": o, "high": h, "low": low, "close": c, "volume": v})
    df = pd.DataFrame(data, index=dates)
    return df
