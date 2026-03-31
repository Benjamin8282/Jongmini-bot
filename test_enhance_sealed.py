"""
강화/증폭(401,402) + 봉인된 자물쇠(501) 타임라인 알림 기능 검증 스크립트.

실제 DNF API를 호출하여:
1. 타임라인 API 응답에 401/402/501 코드가 포함되는지 확인
2. filter_enhance_items / filter_sealed_lock_items 필터링 검증
3. format_enhance_embed / format_sealed_lock_embed 임베드 생성 검증
4. _update_max_time None 안전성 검증
5. _filter_new_items 커서 진행 검증

사용법:
    python test_enhance_sealed.py
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

from core import dnf_api
from core.db import init_db
from core.models import ENHANCE_CODES, SEALED_LOCK_CODES
from tasks.notify_items import (
    filter_enhance_items,
    filter_sealed_lock_items,
    format_enhance_embed,
    format_sealed_lock_embed,
    _all_enhance_items,
    _filter_new_items,
    _update_max_time,
    parse_event_date,
)

KST = timezone(timedelta(hours=9))

# 카시야스 김철완 캐릭터 (API 검증용)
TEST_SERVER = "casillas"
TEST_CHARACTER_NAME = "김철완"
TEST_CHARACTER_ID = "ab590098566252dad7fe024ab17f5fcc"
TEST_ADVENTURE = "테스트모험단"


def print_section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_embed(embed) -> None:
    """Discord Embed 내용을 콘솔에 출력."""
    print(f"  Title: {embed.title}")
    print(f"  Color: #{embed.color.value:06X}" if embed.color else "  Color: None")
    if embed.description:
        for line in embed.description.split("\n"):
            print(f"  | {line}")
    if embed.footer and embed.footer.text:
        print(f"  Footer: {embed.footer.text}")
    print()


async def test_api_response() -> list[dict]:
    """1. 실제 API 호출하여 401/402/501 코드 포함 여부 확인."""
    print_section("1. 타임라인 API 응답 검증")

    now = datetime.now(KST)
    start = (now - timedelta(days=90)).strftime("%Y%m%dT%H%M")
    end = now.strftime("%Y%m%dT%H%M")

    timeline = await dnf_api.fetch_timeline(
        TEST_SERVER, TEST_CHARACTER_ID,
        start_date=start, end_date=end
    )

    if not timeline or "timeline" not in timeline:
        print("  FAIL: 타임라인 응답 없음")
        return []

    rows = timeline["timeline"]["rows"]
    print(f"  총 {len(rows)}건 수신")

    # 코드별 분류
    by_code: dict[int, list] = {}
    for r in rows:
        code = r.get("code")
        by_code.setdefault(code, []).append(r)

    for code in sorted(by_code):
        name = by_code[code][0].get("name", "?")
        count = len(by_code[code])
        marker = " <-- NEW" if code in (401, 402, 501) else ""
        print(f"  코드 {code} ({name}): {count}건{marker}")

    # 검증
    has_enhance = any(c in by_code for c in ENHANCE_CODES)
    has_sealed = 501 in by_code
    print(f"\n  강화/증폭(401/402) 존재: {'PASS' if has_enhance else 'SKIP (해당 기간 없음)'}")
    print(f"  봉인된 자물쇠(501) 존재: {'PASS' if has_sealed else 'SKIP (해당 기간 없음)'}")

    return rows


def test_filter_enhance(rows: list[dict]) -> None:
    """2. filter_enhance_items 필터링 검증."""
    print_section("2. filter_enhance_items 검증")

    all_enhance = _all_enhance_items(rows)
    filtered = filter_enhance_items(rows)

    print(f"  전체 401/402 이벤트: {len(all_enhance)}건")
    print(f"  before >= 10 필터 후: {len(filtered)}건")
    print(f"  필터링된 건수: {len(all_enhance) - len(filtered)}건 (before < 10)")

    # before 값 분포
    before_values = [r.get("data", {}).get("before", 0) for r in all_enhance]
    if before_values:
        print(f"  before 값 범위: {min(before_values)} ~ {max(before_values)}")

    # 필터링된 항목 샘플
    for item in filtered[:3]:
        d = item.get("data", {})
        result_str = "성공" if d.get("result") else "실패"
        print(f"  - {d.get('itemName', '?')} {d.get('before')}→{d.get('after')} ({result_str})")

    # edge case: None before
    test_row = {"code": 402, "data": {"before": None, "after": 11}}
    result = filter_enhance_items([test_row])
    print(f"\n  Edge case (before=None): {'PASS' if len(result) == 0 else 'FAIL'} (필터링됨)")

    # edge case: missing data
    test_row2 = {"code": 401}
    result2 = filter_enhance_items([test_row2])
    print(f"  Edge case (data 없음): {'PASS' if len(result2) == 0 else 'FAIL'} (필터링됨)")


def test_filter_sealed(rows: list[dict]) -> None:
    """3. filter_sealed_lock_items 필터링 검증."""
    print_section("3. filter_sealed_lock_items 검증")

    sealed = filter_sealed_lock_items(rows)
    print(f"  봉인된 자물쇠 이벤트: {len(sealed)}건")

    for item in sealed[:3]:
        d = item.get("data", {})
        booster_str = "부스터 O" if d.get("booster") else "부스터 X"
        print(f"  - {d.get('itemName', '?')} ({booster_str})")


def test_format_enhance_embed() -> None:
    """4. format_enhance_embed 임베드 생성 검증."""
    print_section("4. format_enhance_embed 검증")

    cases = [
        ("증폭 성공 (+11→+12, 티켓)", {
            "code": 402, "date": "2026-03-23 10:08",
            "data": {
                "itemName": "만병을 잉태한 역병의 심장", "itemRarity": "태초",
                "before": 11, "after": 12, "result": True, "safe": False,
                "ticket": {"itemName": "[PC방]100프로 +11 장비 증폭권"}
            }
        }),
        ("증폭 실패 (+10→+11)", {
            "code": 402, "date": "2026-03-26 15:40",
            "data": {
                "itemName": "칠흑의 정화 마법석", "itemRarity": "에픽",
                "before": 10, "after": 11, "result": False, "safe": False
            }
        }),
        ("강화 성공 안전강화 (+10→+11)", {
            "code": 401, "date": "2026-03-20 14:00",
            "data": {
                "itemName": "진실을 보는 자의 목걸이", "itemRarity": "에픽",
                "before": 10, "after": 11, "result": True, "safe": True
            }
        }),
        ("safe 실패 (🛡️ 이모지)", {
            "code": 401, "date": "2026-03-20 14:05",
            "data": {
                "itemName": "진실을 보는 자의 목걸이", "itemRarity": "에픽",
                "before": 10, "after": 11, "result": False, "safe": True
            }
        }),
        ("12강 이상 성공 (🎆 이모지)", {
            "code": 402, "date": "2026-03-23 10:10",
            "data": {
                "itemName": "만병을 잉태한 역병의 심장", "itemRarity": "태초",
                "before": 12, "after": 13, "result": True, "safe": False
            }
        }),
        ("Edge: 날짜 없음", {
            "code": 401, "data": {
                "itemName": "테스트", "itemRarity": "에픽",
                "before": 10, "after": 11, "result": True
            }
        }),
        ("Edge: ticket이 문자열", {
            "code": 402, "date": "2026-03-20 10:00",
            "data": {
                "itemName": "테스트", "itemRarity": "에픽",
                "before": 10, "after": 11, "result": True,
                "ticket": "not_a_dict"
            }
        }),
        ("Edge: result가 문자열 'false'", {
            "code": 402, "date": "2026-03-20 10:00",
            "data": {
                "itemName": "테스트", "itemRarity": "에픽",
                "before": 10, "after": 11, "result": "false"
            }
        }),
    ]

    for label, item in cases:
        print(f"  [{label}]")
        event_date = item.get("date", "")
        embed = format_enhance_embed(TEST_ADVENTURE, TEST_CHARACTER_NAME, item, event_date)
        print_embed(embed)


def test_format_sealed_embed() -> None:
    """5. format_sealed_lock_embed 임베드 생성 검증."""
    print_section("5. format_sealed_lock_embed 검증")

    cases = [
        ("일반 획득", {
            "code": 501, "date": "2026-03-05 23:15",
            "data": {
                "itemName": "[3차]모험가 클럽 전용 아바타 풀세트 상자",
                "booster": False
            }
        }),
        ("부스터 x2 획득", {
            "code": 501, "date": "2026-03-05 23:20",
            "data": {
                "itemName": "[3차]모험가 클럽 전용 아바타 풀세트 상자",
                "booster": True
            }
        }),
        ("Edge: booster가 문자열 'false'", {
            "code": 501, "date": "2026-03-05 23:25",
            "data": {
                "itemName": "테스트 아이템",
                "booster": "false"
            }
        }),
        ("Edge: 날짜 없음", {
            "code": 501,
            "data": {"itemName": "테스트", "booster": False}
        }),
    ]

    for label, item in cases:
        print(f"  [{label}]")
        event_date = item.get("date", "")
        embed = format_sealed_lock_embed(TEST_ADVENTURE, TEST_CHARACTER_NAME, item, event_date)
        print_embed(embed)


def test_update_max_time() -> None:
    """6. _update_max_time None 안전성 검증."""
    print_section("6. _update_max_time None 안전성 검증")

    dt1 = datetime(2026, 3, 31, 12, 0)
    dt2 = datetime(2026, 3, 31, 13, 0)

    cases = [
        ("(None, None)", None, None, None),
        ("(None, dt1)", None, dt1, dt1),
        ("(dt1, None)", dt1, None, dt1),
        ("(dt1, dt2)", dt1, dt2, dt2),
        ("(dt2, dt1)", dt2, dt1, dt2),
    ]

    all_pass = True
    for label, a, b, expected in cases:
        result = _update_max_time(a, b)
        status = "PASS" if result == expected else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"  {label} = {result} ... {status}")

    print(f"\n  종합: {'ALL PASS' if all_pass else 'FAIL'}")


def test_filter_new_items_cursor() -> None:
    """7. _filter_new_items 커서 진행 검증."""
    print_section("7. _filter_new_items 커서 진행 검증")

    base_time = datetime(2026, 3, 31, 12, 0)

    # 케이스 1: 새 이벤트 있음
    rows = [
        {"date": "2026-03-31 12:05", "code": 402, "data": {"before": 11}},
        {"date": "2026-03-31 12:10", "code": 402, "data": {"before": 12}},
    ]
    new_items, max_time = _filter_new_items(rows, base_time)
    assert len(new_items) == 2, f"FAIL: expected 2, got {len(new_items)}"
    assert max_time == datetime(2026, 3, 31, 12, 10), f"FAIL: max_time={max_time}"
    print("  케이스 1 (새 이벤트 있음): PASS")

    # 케이스 2: 새 이벤트 없음 (모두 이전)
    old_rows = [
        {"date": "2026-03-31 11:50", "code": 402, "data": {"before": 10}},
    ]
    new_items2, max_time2 = _filter_new_items(old_rows, base_time)
    assert len(new_items2) == 0, f"FAIL: expected 0, got {len(new_items2)}"
    assert max_time2 == base_time, f"FAIL: max_time should be base_time"
    print("  케이스 2 (새 이벤트 없음): PASS")

    # 케이스 3: last_time=None (첫 실행)
    new_items3, max_time3 = _filter_new_items(rows, None)
    assert len(new_items3) == 2, f"FAIL: expected 2, got {len(new_items3)}"
    assert max_time3 == datetime(2026, 3, 31, 12, 10)
    print("  케이스 3 (last_time=None 첫 실행): PASS")

    # 케이스 4: 빈 리스트
    new_items4, max_time4 = _filter_new_items([], None)
    assert len(new_items4) == 0
    assert max_time4 is None
    print("  케이스 4 (빈 리스트, last_time=None): PASS")

    # 케이스 5: 날짜 형식 오류
    bad_rows = [{"date": "invalid", "code": 501}]
    new_items5, max_time5 = _filter_new_items(bad_rows, base_time)
    assert len(new_items5) == 0
    print("  케이스 5 (날짜 형식 오류): PASS")

    print("\n  종합: ALL PASS")


async def main():
    print("=" * 60)
    print("  강화/증폭/봉인된 자물쇠 타임라인 알림 검증")
    print("=" * 60)

    # 순수 함수 테스트 (API 불필요)
    test_update_max_time()
    test_filter_new_items_cursor()
    test_format_enhance_embed()
    test_format_sealed_embed()

    # API 연동 테스트
    rows = await test_api_response()
    if rows:
        test_filter_enhance(rows)
        test_filter_sealed(rows)

    print_section("검증 완료")


if __name__ == "__main__":
    asyncio.run(init_db())
    asyncio.run(dnf_api.preload_item_cache())
    asyncio.run(main())
