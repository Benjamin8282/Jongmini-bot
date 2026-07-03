"""활동지수 파이프라인 동작 검증 데모 (합성 데이터).

실제 DB 없이 core.activity_index 파이프라인의 핵심 성질을 확인한다:
1) 안정 구간 → 지수가 100 부근 유지
2) 지속적 2배 증가 → 증가분이 지수 수준(level)에 유지 (평균회귀 없음)
3) 3일 이벤트 급증 → 지수에 그대로 반영 + Hampel 플래그
4) 전 아이템 수집 공백일 → 0으로 지어내지 않고 결측(차트 갭) 처리
5) 수집 가동일의 단일 아이템 무거래 → 실제 0으로 집계 (날짜 유지)
6) 관측 15일 미만 아이템 제외 및 item_count 정합성
7) 시세 감시 해제(고아) 아이템 → 동결 이후 0채움 금지, MAD 스팸 없음
8) 전 아이템 꼬리 공백 → 마지막 표시일이 실제 마지막 수집일 (조작 없음)
9) get_daily_volumes가 진행 중인 오늘(KST)을 제외하는지 (임시 DB)

실행: .venv/Scripts/python.exe activity_index_verify_demo.py
"""
import asyncio
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np

import core.activity_index as ai

PASS = "  [PASS]"
FAIL = "  [FAIL]"
_failures = []


def check(cond: bool, message: str):
    print(f"{PASS if cond else FAIL} {message}")
    if not cond:
        _failures.append(message)


def _date_strs(n_days: int) -> list[str]:
    """어제로 끝나는 n_days개의 날짜 문자열 (당일 제외 시맨틱과 동일)."""
    yesterday = date.today() - timedelta(days=1)
    return [
        (yesterday - timedelta(days=n_days - 1 - i)).isoformat()
        for i in range(n_days)
    ]


def _stub_db(volumes_by_item: dict[str, list[float]], n_days: int,
             watched: set[str] | None = None):
    """DB 함수 스텁 생성. 실제 DB처럼 거래량 0인 날은 행을 반환하지 않는다."""
    dates = _date_strs(n_days)
    watched_set = set(volumes_by_item) if watched is None else set(watched)

    async def fake_basket():
        return [
            {"item_id": name, "item_name": name}
            for name in volumes_by_item
        ]

    async def fake_watch():
        return [
            {"item_id": name, "item_name": name}
            for name in watched_set
        ]

    async def fake_volumes(item_id: str, days: int):
        vols = volumes_by_item[item_id]
        item_dates = dates[-len(vols):]
        return [
            {"date": d, "volume": float(v)}
            for d, v in zip(item_dates, vols)
            if v is not None and v > 0
        ]

    return fake_basket, fake_watch, fake_volumes


async def run_pipeline(volumes_by_item: dict, n_days: int = 90,
                       display_days: int = 30,
                       watched: set[str] | None = None):
    fake_basket, fake_watch, fake_volumes = _stub_db(
        volumes_by_item, n_days, watched
    )
    with patch.object(ai, "get_basket_items", fake_basket), \
         patch.object(ai, "get_all_watch_items", fake_watch), \
         patch.object(ai, "get_daily_volumes", fake_volumes):
        return await ai.calc_activity_index(display_days=display_days)


def _stable(rng, base: float, n: int) -> list[float]:
    return list(np.maximum(rng.normal(base, base * 0.03, n), 1.0))


async def case1_stable():
    print("\n[케이스 1] 안정 거래량 → 지수 100 부근")
    rng = np.random.default_rng(42)
    result = await run_pipeline({
        "물약": _stable(rng, 1000, 90),
        "결정": _stable(rng, 3000, 90),
        "정수": _stable(rng, 500, 90),
    })
    check(result is not None, "결과 생성됨")
    if result:
        values = result["index"]
        check(len(result["dates"]) == 30, f"표시 30일 (실제 {len(result['dates'])}일)")
        check(all(80 <= v <= 120 for v in values),
              f"전 구간 100 부근 (범위 {min(values):.1f}~{max(values):.1f})")
        check(result["item_count"] == 3, f"item_count=3 (실제 {result['item_count']})")
        check(result["baseline_days"] == 90,
              f"baseline_days가 실제 스팬 반영 (90, 실제 {result['baseline_days']})")


async def case2_sustained_jump():
    print("\n[케이스 2] 60일차부터 지속적 2배 증가 → 수준 유지 (평균회귀 없음)")
    rng = np.random.default_rng(7)

    def jumped(base):
        pre = _stable(rng, base, 60)
        post = _stable(rng, base * 2, 30)
        return pre + post

    result = await run_pipeline({
        "물약": jumped(1000), "결정": jumped(3000), "정수": jumped(500),
    })
    check(result is not None, "결과 생성됨")
    if result:
        values = result["index"]
        last10_mean = float(np.mean(values[-10:]))
        check(last10_mean > 125,
              f"점프 20~30일 후에도 지수가 상승 수준 유지 (마지막 10일 평균 {last10_mean:.1f}%)")
        check(values[-1] > 125,
              f"마지막 값이 100으로 회귀하지 않음 (현재 {values[-1]:.1f}%)")


async def case3_event_spike():
    print("\n[케이스 3] 3일 이벤트 급증(×3) → 지수 반영 + Hampel 플래그")
    rng = np.random.default_rng(11)

    def spiked(base):
        vols = _stable(rng, base, 90)
        for i in range(80, 83):
            vols[i] = base * 3
        return vols

    result = await run_pipeline({
        "물약": spiked(1000), "결정": spiked(3000), "정수": spiked(500),
    })
    check(result is not None, "결과 생성됨")
    if result:
        spike_dates = _date_strs(90)[80:83]
        idx_map = dict(zip(result["dates"], result["index"]))
        spike_vals = [idx_map[d] for d in spike_dates if d in idx_map]
        check(len(spike_vals) == 3, "스파이크 3일 모두 표시 구간에 존재")
        check(all(v > 150 for v in spike_vals),
              f"스파이크가 지수에 반영됨 (값 {[f'{v:.0f}' for v in spike_vals]})")
        flagged = result["spike_stats"]["total_flagged"]
        check(flagged >= 3, f"Hampel 플래그 감지 (총 {flagged}건)")


async def case4_global_gap():
    print("\n[케이스 4] 전 아이템 수집 공백 2일 → 0으로 조작하지 않고 결측(갭) 처리")
    rng = np.random.default_rng(23)

    def with_gap(base):
        vols = _stable(rng, base, 90)
        vols[84] = 0.0  # 행 미반환 → 전 아이템 공백일
        vols[85] = 0.0
        return vols

    result = await run_pipeline({
        "물약": with_gap(1000), "결정": with_gap(3000), "정수": with_gap(500),
    })
    check(result is not None, "결과 생성됨")
    if result:
        gap_dates = [_date_strs(90)[84], _date_strs(90)[85]]
        check(all(d not in result["dates"] for d in gap_dates),
              "전 아이템 공백일은 '활동 전무 0'으로 표시되지 않음 (갭)")
        check(len(result["dates"]) == 28,
              f"공백 2일 제외한 28일 표시 (실제 {len(result['dates'])}일)")
        values = result["index"]
        check(all(80 <= v <= 120 for v in values),
              f"공백 주변 지수 안정 (범위 {min(values):.1f}~{max(values):.1f})")


async def case5_single_item_zero():
    print("\n[케이스 5] 수집 가동일의 단일 아이템 무거래 → 실제 0으로 집계, 날짜 유지")
    rng = np.random.default_rng(29)

    vols_a = _stable(rng, 1000, 90)
    vols_a[86] = 0.0  # 물약만 무거래, 나머지는 정상 거래
    result = await run_pipeline({
        "물약": vols_a,
        "결정": _stable(rng, 3000, 90),
        "정수": _stable(rng, 500, 90),
    })
    check(result is not None, "결과 생성됨")
    if result:
        zero_date = _date_strs(90)[86]
        check(zero_date in result["dates"],
              "단일 아이템 무거래일이 차트에서 사라지지 않음")
        idx_map = dict(zip(result["dates"], result["index"]))
        v = idx_map.get(zero_date)
        check(v is not None and 80 <= v <= 115,
              f"중앙값 지수는 안정 (3개 중 1개 0 → 중앙값 유지, 값 {v})")


async def case6_min_observations():
    print("\n[케이스 6] 관측 15일 미만 아이템 제외 + 최소 3개 보장")
    rng = np.random.default_rng(31)
    result = await run_pipeline({
        "물약": _stable(rng, 1000, 90),
        "결정": _stable(rng, 3000, 90),
        "신규": _stable(rng, 500, 10),
    })
    check(result is None, "유효 아이템 2개면 None 반환 (단일/이중 아이템 지수 방지)")

    result = await run_pipeline({
        "물약": _stable(rng, 1000, 90),
        "결정": _stable(rng, 3000, 90),
        "정수": _stable(rng, 700, 90),
        "신규": _stable(rng, 500, 10),
    })
    check(result is not None, "유효 3개면 정상 산출")
    if result:
        check(result["item_count"] == 3,
              f"item_count가 실제 참여 수 반영 (3, 실제 {result['item_count']})")


async def case7_orphaned_item():
    print("\n[케이스 7] 시세 감시 해제된 바스켓 아이템 → 동결 이후 0채움 금지")
    rng = np.random.default_rng(37)

    orphan_vols = _stable(rng, 800, 90)
    for i in range(60, 90):
        orphan_vols[i] = 0.0  # 60일차부터 수집 중단 (행 미반환)

    result = await run_pipeline(
        {
            "물약": _stable(rng, 1000, 90),
            "결정": _stable(rng, 3000, 90),
            "정수": _stable(rng, 500, 90),
            "고아": orphan_vols,
        },
        watched={"물약", "결정", "정수"},  # 고아는 감시 목록에서 빠짐
    )
    check(result is not None, "결과 생성됨")
    if result:
        check(result["item_count"] == 3,
              f"동결 아이템은 표시 구간 참여 수에서 제외 (3, 실제 {result['item_count']})")
        orphan_mentions = [
            item for items in result["outliers"].values()
            for item in items if "고아" in item
        ]
        check(len(orphan_mentions) == 0,
              f"동결 아이템 MAD 이상치 스팸 없음 (언급 {len(orphan_mentions)}건)")
        values = result["index"]
        check(all(80 <= v <= 120 for v in values),
              f"동결 아이템이 지수를 끌어내리지 않음 (범위 {min(values):.1f}~{max(values):.1f})")


async def case8_stale_tail():
    print("\n[케이스 8] 전 아이템 꼬리 공백 3일 → 마지막 표시일 = 실제 마지막 수집일")
    rng = np.random.default_rng(41)

    def stale(base):
        vols = _stable(rng, base, 90)
        for i in range(87, 90):
            vols[i] = 0.0  # 최근 3일 전 아이템 공백 (수집 중단/서버 다운 등)
        return vols

    result = await run_pipeline({
        "물약": stale(1000), "결정": stale(3000), "정수": stale(500),
    })
    check(result is not None, "결과 생성됨")
    if result:
        expected_last = _date_strs(90)[86]
        check(result["dates"][-1] == expected_last,
              f"마지막 표시일이 실제 마지막 수집일 (기대 {expected_last}, 실제 {result['dates'][-1]})")
        values = result["index"]
        check(all(v > 50 for v in values[-3:]),
              "꼬리 공백이 허위 급락(0)으로 표시되지 않음")


async def case9_today_excluded_in_db():
    print("\n[케이스 9] get_daily_volumes: 진행 중인 오늘(KST) 제외")
    import core.db as db
    from core.time_utils import KST

    tmpdir = tempfile.mkdtemp()
    db.DB_PATH = Path(tmpdir) / "verify.db"
    db._conn = None
    await db.init_db()

    now_kst = datetime.now(KST)
    today_str = now_kst.strftime("%Y-%m-%d")
    yesterday_str = (now_kst - timedelta(days=1)).strftime("%Y-%m-%d")
    await db.save_auction_prices([
        {"item_id": "test", "sold_date": f"{yesterday_str} 12:00:00",
         "unit_price": 100, "price": 100, "count": 5},
        {"item_id": "test", "sold_date": f"{today_str} 01:00:00",
         "unit_price": 100, "price": 100, "count": 7},
    ])

    rows = await db.get_daily_volumes("test", 30)
    dates_in_db = {r["date"] for r in rows}
    check(yesterday_str in dates_in_db, "어제(완결일) 데이터 포함")
    check(today_str not in dates_in_db, "오늘(부분일) 데이터 제외")
    volume = next((r["volume"] for r in rows if r["date"] == yesterday_str), None)
    check(volume == 5, f"어제 거래량 정확 (5, 실제 {volume})")
    await db.close_db()


async def main():
    await case1_stable()
    await case2_sustained_jump()
    await case3_event_spike()
    await case4_global_gap()
    await case5_single_item_zero()
    await case6_min_observations()
    await case7_orphaned_item()
    await case8_stale_tail()
    await case9_today_excluded_in_db()

    print("\n" + "─" * 50)
    if _failures:
        print(f"실패 {len(_failures)}건:")
        for f in _failures:
            print(f"  - {f}")
        raise SystemExit(1)
    print("전체 검증 통과")


if __name__ == "__main__":
    asyncio.run(main())
