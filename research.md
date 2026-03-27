# Jongmini-bot 코드베이스 상세 분석 보고서

> 분석 일자: 2026-03-26
> 현재 버전: v2.4.0
> 기술 스택: Python 3.11+, discord.py 2.5.2, aiosqlite, aiohttp, matplotlib, pandas, statsmodels, ruptures

---

## 1. 프로젝트 개요

**종미니 봇(Jongmini Bot)** — 던전앤파이터(DNF) 오픈 API를 활용한 실시간 득템 알림 및 경매장 시세 분석 디스코드 봇.

핵심 기능 4가지:
1. **실시간 득템 알림**: 등록된 캐릭터의 타임라인을 20초 간격으로 모니터링하여 레벨 115 이상 에픽/태초 아이템 획득 시 디스코드 채널에 알림
2. **경매장 시세 분석**: 30초 간격으로 경매장 거래 데이터를 수집하고, 캔들스틱 차트 + RSI/MA 기술 분석 제공
3. **게임 경제 지표**: 활동지수(거래량 기반)와 DUNSPY 종합지수를 통해 게임 경제 건전성 모니터링
4. **던담 랭킹**: 외부 던담(dundam.xyz) API를 통한 캐릭터/모험단 딜량 랭킹 조회

---

## 2. 프로젝트 구조

```
Jongmini-bot/
├── main.py                     # 진입점 (227줄) — JongminiBot 클래스, 이벤트 핸들링
├── CLAUDE.md                   # 프로젝트 가이드
├── Dockerfile                  # Python 3.11 + 한글 폰트 + Cython 빌드
├── requirements.txt            # 18개 의존성
├── pytest.ini                  # asyncio_mode = auto
│
├── core/                       # 핵심 비즈니스 로직 (14 파일)
│   ├── db.py                   # (1154줄) SQLite 데이터 접근 계층
│   ├── dnf_api.py              # (345줄) 네오플 DNF API 래퍼
│   ├── dundam_api.py           # (198줄) 던담 외부 랭킹 API
│   ├── dundam_queue.py         # 던담 API 큐 매니저 (레이트 리밋)
│   ├── avatar_market_api.py    # 아바타 마켓 API 래퍼
│   ├── chart.py                # (787줄) matplotlib/mplfinance 차트 생성
│   ├── analysis.py             # (490줄) 기술 분석 (RSI, MA, 상관관계)
│   ├── activity_index.py       # (453줄) 활동지수 계산 파이프라인
│   ├── dunspy_index.py         # (164줄) DUNSPY 종합지수 산출
│   ├── models.py               # (36줄) 서버 매핑, 희귀도 가중치
│   ├── time_utils.py           # (81줄) KST 기준 기간 계산
│   ├── chat_moderator.py       # (319줄) 콘텐츠 모더레이션 (비활성)
│   ├── logger.py               # (68줄) KST 로깅 (1MB 로테이션, 14일 보존)
│   └── _sftp_auth.py           # SFTP 인증 (Docker에서 .so로 컴파일)
│
├── commands/                   # 디스코드 슬래시 커맨드 (22 파일)
│   ├── hello.py                # /hello — 봇 인사
│   ├── register.py             # /등록 — 캐릭터 등록
│   ├── total.py                # /전체조회 — 등록 캐릭터 모험단별 조회
│   ├── set_output_channel.py   # /출력채널 — 아이템/경제 알림 채널 분리
│   ├── today_status.py         # /오늘현황
│   ├── weekly_status.py        # /주간현황
│   ├── monthly_status.py       # /월간현황
│   ├── season_status.py        # /시즌현황
│   ├── weekly_character_status.py # /주간캐릭터현황
│   ├── dundam_ranking.py       # /던담순위 (딜러/버퍼)
│   ├── dundam_exclusion.py     # /던담검색제외
│   ├── adventure_dundam_ranking.py # /모험단던담순위
│   ├── auction_watch.py        # /시세등록, /시세해제, /시세목록
│   ├── auction_chart.py        # /시세차트 — 캔들스틱 + 기술 분석
│   ├── auction_compare.py      # /시세비교 — 아이템 간 시세 비교
│   ├── auction_overview.py     # /시세현황 — 24시간 시세 변동 요약
│   ├── activity_basket.py      # /바스켓등록, /바스켓해제, /바스켓목록, /활동지수
│   ├── alert_settings.py       # /시세알림, /시세알림목록, /시세알림해제
│   ├── dunspy.py               # /던스피 — DUNSPY 종합지수
│   ├── avatar_search.py        # /아바타검색
│   ├── avatar_price.py         # /아바타시세
│   ├── export_data.py          # /데이터내보내기 — Excel SFTP 업로드
│   └── rest_days.py            # /쉬었음 — 미접속 일수 추적
│
├── tasks/                      # 백그라운드 태스크 (8 파일)
│   ├── notify_items.py         # 20초 간격 타임라인 모니터링
│   ├── daily_aggregation.py    # 일간 집계 (06:00 KST)
│   ├── weekly_aggregation.py   # 주간 집계 (목요일 06:00 KST)
│   ├── monthly_aggregation.py  # 월간 집계 (1일 06:00 KST)
│   ├── poll_auction_prices.py  # 30초 간격 경매장 시세 폴링
│   ├── price_alert.py          # 시세 급등/급락/신고가 알림 감지
│   ├── morning_briefing.py     # 매일 06:00 경제 브리핑
│   └── weekly_character_aggregation.py # 캐릭터별 주간 집계 (비활성)
│
├── tests/                      # 테스트 (10 파일)
│   ├── conftest.py             # 공통 fixture (test_db, sample_price_records, sample_ohlc)
│   ├── test_analysis.py
│   ├── test_chart.py
│   ├── test_db.py
│   ├── test_dnf_api.py
│   ├── test_dundam_api.py
│   ├── test_morning_briefing.py
│   ├── test_price_alert.py
│   └── test_time_utils.py
│
├── docs/                       # 문서
│   ├── dnf_api_reference.md    # DNF API 엔드포인트 레퍼런스
│   ├── activity_index_algorithm.md # 활동지수 알고리즘 설명서
│   └── api_responses/          # API 응답 샘플 JSON (35개 파일)
│
├── data/                       # 런타임 데이터
│   └── characters.db           # SQLite DB
│
├── logs/                       # 로그 파일 (14일 보존)
│
└── (데모/유틸리티)
    ├── dnf_api_demo.py
    ├── dnf_api_timeline_demo.py
    ├── dnf_api_timeline_demo_lock.py
    ├── api_doc_collector.py
    ├── crawl_demo.py
    └── setup_sftp_auth.py      # Cython 빌드 스크립트
```

---

## 3. 진입점 분석 (main.py)

### 3.1 JongminiBot 클래스

```python
class JongminiBot(commands.Bot):
```

- `AsyncIOScheduler` (KST 타임존)으로 정기 작업 관리
- Discord intents: `default` + `messages` + `message_content`
- `ChatModerator` 인스턴스 (현재 비활성)
- `DundamQueueManager` 싱글턴

### 3.2 생명주기

| 단계 | 함수 | 수행 작업 |
|------|------|----------|
| 초기화 | `__init__()` | 스케줄러, 인텐트, 모더레이터, 던담큐 생성 |
| 셋업 | `setup_hook()` | DB 초기화, 아이템 캐시 프리로드, 아바타 캐시 프리로드, **30개 슬래시 커맨드 등록** |
| 준비 | `on_ready()` | 길드별 커맨드 sync (최초 1회), 글로벌 커맨드 정리, **5개 백그라운드 태스크 시작**, 던담큐 시작, 스케줄러 시작 |
| 메시지 | `on_message()` | 메시지 로깅, 커맨드 처리 (모더레이터는 주석 처리됨) |
| 종료 | `close()` | HTTP 세션 종료, DB 커넥션 종료 |

### 3.3 백그라운드 태스크 등록

```python
_BACKGROUND_TASKS = [
    ("notify_task",              periodic_notify,          "타임라인 아이템 알림"),
    ("daily_aggregation_task",   daily_aggregation_task,   "일간 모험단 집계"),
    ("weekly_aggregation_task",  weekly_aggregation_task,  "주간 모험단 집계"),
    ("monthly_aggregation_task", monthly_aggregation_task, "월간 모험단 집계"),
    ("auction_poll_task",        poll_auction_prices,      "경매장 시세 폴링"),
]
```

`_should_start_task()`로 중복 시작 방지: 속성이 없거나 `.done()`이면 새로 시작.

### 3.4 커맨드 동기화 전략

글로벌 sync 대신 **길드별 sync** 사용:
1. `copy_global_to(guild=guild)` — 글로벌 커맨드를 길드로 복사
2. `tree.sync(guild=guild)` — 길드별 즉시 반영
3. `clear_commands(guild=None)` + `tree.sync()` — 글로벌 커맨드 제거 (중복 방지)

이점: 봇 재배포 시 즉시 반영, 추방/재초대 불필요

---

## 4. 핵심 모듈 상세 분석 (core/)

### 4.1 데이터베이스 계층 (core/db.py — 1154줄)

#### 연결 관리
- 글로벌 영속 연결 (`_conn`)
- PRAGMA 설정: WAL 모드, NORMAL sync, 8MB 캐시, MEMORY temp_store, 5초 busy timeout
- DB 파일 경로: `data/characters.db`

#### 테이블 스키마 (16개)

| 테이블 | PK | 용도 | 특이사항 |
|--------|-----|------|---------|
| `characters` | character_id | 캐릭터 기본 정보 | INSERT OR REPLACE |
| `registrations` | (user_id, character_id) | 사용자-캐릭터 매핑 | FK → characters |
| `item_cache` | item_id | 아이템 장착 레벨 캐시 | 3-tier 캐시의 2단계 |
| `output_channels` | guild_id | 길드별 출력 채널 설정 | item/economy 분리 + fallback |
| `character_last_checked` | character_id | 마지막 타임라인 체크 시간 | 득템 알림 중복 방지 |
| `daily_aggregation_log` | id | 일간 집계 실행 이력 | 미실행 감지용 |
| `adventure_exclusions` | (adventure_name, server_id) | 모험단 검색 제외 | 던담순위 필터링 |
| `auction_watch_items` | item_id | 경매장 시세 감시 아이템 | 등록자/시간 추적 |
| `auction_price_history` | id | 경매장 거래 가격 이력 | UNIQUE(item_id, sold_date, unit_price, count) |
| `user_alert_settings` | id | 사용자별 DM 시세 알림 | UNIQUE(user_id, item_id, alert_type) |
| `activity_basket` | item_id | 활동지수 바스켓 아이템 | |
| `dundam_ranking_cache` | (character_id, server_id, mode) | 던담 랭킹 캐시 | 실시간 실패 시 폴백 |
| `job_skill_options` | job_key | 직업 스킬 옵션 캐시 | |
| `dundam_daily_usage` | date | 던담 API 일일 사용량 | ON CONFLICT DO UPDATE |
| `user_recent_items` | (user_id, item_name) | 시세 최근 검색 아이템 | 최대 10개 자동 정리 |
| `rest_days` | id | 모험단별 미접속 일수 | UNIQUE(adventure_name, rest_date) |

12개 인덱스로 성능 최적화.

#### 주요 함수 카테고리

**캐릭터 관리** (8개):
- `save_character()`, `register_character()`, `get_characters_by_adventure_name()`, `get_characters_by_user()`, `get_all_characters_grouped_by_adventure()`, `get_all_characters()`, `get_active_characters()`, `update_character_name()`

**출력 채널 관리** (4개):
- `save_output_channel()`, `get_output_channel()`, `save_typed_output_channel()`, `get_all_output_channels()`
- 타입별 채널 미설정 시 기존 `channel_id`로 폴백 (하위 호환)

**경매장/시세** (9개):
- `add_watch_item()`, `remove_watch_item()`, `get_all_watch_items()`, `get_watch_item_by_name()`
- `save_auction_prices()` (벌크 INSERT OR IGNORE), `get_price_history()`, `cleanup_old_price_history()`
- `get_daily_volumes()`, `get_daily_avg_prices()` (활동지수/DUNSPY용 집계 쿼리)

**사용자 알림** (4개):
- `upsert_user_alert()` (ON CONFLICT DO UPDATE), `get_user_alerts()`, `delete_user_alert()`, `disable_user_alert()`

**던담** (5개):
- `get_dundam_daily_usage()`, `increment_dundam_daily_usage()`, `save_dundam_ranking_cache()`, `get_dundam_ranking_cache()`, `get_dundam_ranking_cache_timestamp()`

---

### 4.2 DNF API 래퍼 (core/dnf_api.py — 345줄)

**Base URL**: `https://api.neople.co.kr/df`

#### HTTP 세션
- `TCPConnector(limit=50, per_host=10)` — 전체 50 동시연결, 호스트당 10
- 타임아웃: total=30s, connect=10s
- 지연 초기화 (`get_session()`)

#### API 엔드포인트

| 함수 | 엔드포인트 | 용도 |
|------|-----------|------|
| `search_characters()` | GET `/servers/{sid}/characters` | 캐릭터 이름 검색 |
| `get_character_details()` | GET `/servers/{sid}/characters/{cid}` | 캐릭터 상세 정보 |
| `get_character_image_url()` | URL 생성만 | 캐릭터 이미지 URL |
| `get_character_image_bytes()` | GET 이미지 바이트 | 캐릭터 PNG 이미지 |
| `fetch_timeline()` | GET `/timeline` | 캐릭터 타임라인 (단일 페이지) |
| `fetch_timeline_with_pagination()` | GET `/timeline` (반복) | 전체 타임라인 (페이지네이션) |
| `fetch_auction_sold()` | GET `/auction-sold` | 경매장 거래 내역 (400건 제한) |
| `fetch_item_search()` | GET `/items` | 아이템 검색 (30건 제한) |
| `fetch_item_detail()` | GET `/items/{id}` | 아이템 상세 (레벨 정보) |

#### 3-tier 아이템 캐싱 전략

```
1. ITEM_DETAIL_MEMCACHE (인메모리 dict)
   ↓ miss
2. item_cache DB 테이블
   ↓ miss
3. DNF API /items/{id} 호출
   → 성공 시 1+2 모두에 캐시 저장
```

`preload_item_cache()`: 봇 시작 시 DB의 전체 item_cache를 메모리에 로드

#### 타임라인 코드 필터

| code | 설명 |
|------|------|
| 504 | 항아리&상자 |
| 505 | 던전 드랍 |
| 507 | 레이드 카드 보상 |
| 508 | 기타 |
| 513 | 던전 카드 보상 |
| 550 | 서약 획득(던전 드랍) |
| 551 | 서약 획득(레이드 카드 보상) |
| 552 | 서약 획득(항아리&상자) |
| 553 | 서약 획득(업그레이드) |
| 554 | 서약 획득(제작서) |
| 555 | 서약 획득(무기고) |
| 556 | 서약 초월(초월의 돌) |

- `code=505,504,507,508,513,550,551,552,553,554,555,556`
- limit=100 (페이지당)
- 페이지네이션: `next` 토큰 기반 반복 조회

---

### 4.3 던담 API 통합 (core/dundam_api.py — 198줄)

**Base URL**: `https://dundam.xyz/dat/viewData.jsp`

#### 캐싱
- TTL 기반 10분 캐시 (`_cache` dict)
- 키: 캐릭터 ID + 모드

#### 재시도 로직
- 3회 재시도 (지수 백오프: `2^attempt + random(0,1)`)
- 503, 429 응답 시 재시도
- 403은 치명적 에러 (즉시 종료)

#### 동시성 제어
- `fetch_all_with_rate_limit()`: 세마포어 기반, 초당 5요청 제한
- `asyncio.as_completed()` 패턴으로 완료 순서대로 결과 수집

#### 던담 큐 매니저 (core/dundam_queue.py)
- FIFO 큐 + 레이트 리밋 (0.2초 최소 간격)
- 일일 한도 추적 (기본 20,000 호출/일, `DUNDAM_DAILY_LIMIT` 환경변수)
- 싱글턴 패턴, 워커 코루틴

---

### 4.4 차트 생성 (core/chart.py — 787줄)

#### 다크 테마 팔레트
- 배경: `#1a1a2e`, 패널: `#16213e`, 텍스트: `#e0e0e0`, 그리드: `#2a2a4a`
- 상승: `#ff4757` (빨강), 하락: `#3498ff` (파랑), 강조: `#ffd32a` (금색)

#### 차트 종류 (5가지)

| 차트 | 함수 | 용도 |
|------|------|------|
| 캔들스틱 | `generate_candlestick_chart()` | 시세 분석 (MA 5/10/20/60 오버레이) |
| 비교 차트 | `generate_comparison_chart()` | 2개 아이템 가격 비교 (듀얼 Y축) |
| 오버뷰 | `generate_overview_chart()` | 24시간 전체 아이템 스파크라인 |
| 활동지수 | `generate_activity_chart()` | 활동지수 + 변화점 + 이상치 마커 |
| DUNSPY | `generate_dunspy_chart()` | 종합지수 (1000 기준선) |

#### 기술적 세부사항
- `threading.Lock()` — matplotlib 전역 상태 보호 (비동기 환경에서 스레드 안전)
- IQR 기반 이상치 필터링 (multiplier=3.0, 필터링 후 50% 미만이면 원본 유지)
- OHLC 집계: 1분~1일 간격 리샘플링
- 한글 폰트: Windows="Malgun Gothic", Linux="NanumGothic"
- PNG 출력: dpi=120, BytesIO 반환

---

### 4.5 기술 분석 (core/analysis.py — 490줄)

#### 기술 지표

| 지표 | 함수 | 파라미터 |
|------|------|---------|
| RSI | `calc_rsi()` | period=14 |
| MA 정렬 | `calc_ma_alignment()` | MA5, MA10, MA20 비교 |
| MA 이격도 | `calc_ma_disparity()` | (price - MA20) / MA20 × 100 |
| 거래량 급증 | `calc_volume_surge()` | 최근5/최근20 비율 ≥ 1.5 |
| 가격-거래량 괴리 | `calc_price_volume_divergence()` | 가격↑거래량↓ or 반대 |
| 상관관계 | `calc_correlation()` | 피어슨 r (최소 10 겹침) |

#### 종합 점수 시스템

```
trend_score      → bullish=+2, bearish=-2, neutral=0
rsi_score        → <30=+1(과매도), >70=-1(과매수)
surge_score      → 급증+상승=+1, 급증+하락=-1
divergence_score → 괴리 방향에 따라 ±1
disparity_score  → |이격도|>10 → ±1

합산 → 의견:
  ≥3: "강한 매수"
  ≥1: "매수 우위"
   0: "관망"
 ≥-2: "매도 우위"
  <-2: "강한 매도"
```

#### 가격 추천 시스템 (`recommend_prices()`)
- 최근 24~168시간 내 20건 이상 데이터 필요
- IQR 필터링 → 거래량 가중 가격 목록 생성
- P60(안정), P80(적정), P95(도전) 백분위 반환

---

### 4.6 활동지수 파이프라인 (core/activity_index.py — 453줄)

```
원본 거래량
    │
[Phase A] Hampel 필터 ── 이벤트성 스파이크 제거 (window=7, threshold=3.0)
    │
[Phase B] STL 분해 ──── 요일 주기성 제거 (period=7, robust=True)
    │
[Phase D] PELT 변화점 ── 시즌 업데이트 체제 전환 감지 (min_size=14, penalty=5.0)
    │
체제별 정규화 (30일 이동평균 대비 %)
    │
일별 중앙값 = 활동지수
    │
[Phase C] MAD 이상치 ── 잔여 이상치 플래그 (표시용, 제거 안 함)
```

**핵심 알고리즘**:
- **Hampel**: 이동 중앙값 + MAD × 3 × 1.4826 기준 스파이크 교체
- **STL**: Trend + Residual 사용, Seasonal(요일 효과) 제거
- **PELT**: RBF 커널, 2주 최소 체제, 체제별 30일 MA 정규화
- **MAD**: 정규화 후 교차 아이템 이상치 감지 (표시만, 제거 안 함)
- **집계**: 아이템별 중앙값 → 극단값 하나에 흔들리지 않음

---

### 4.7 DUNSPY 종합지수 (core/dunspy_index.py — 164줄)

- 기준값: 1000.0
- 기준일: 바스켓 전 아이템이 존재하는 최초 날짜
- 계산: `normalized = df / base_prices × 1000`, 아이템 간 동일 가중 평균
- 최소 2개 바스켓 아이템, 5일 이상 데이터 필요
- 구성종목별 변화율 계산 및 정렬

---

### 4.8 모델/상수 (core/models.py — 36줄)

```python
SERVER_MAP = {"all": "전체", "anton": "안톤", "bakal": "바칼", ...}  # 9개 서버
ALLOWED_RARITIES = {"에픽", "태초"}
RARITY_WEIGHTS = {"태초": 100, "에픽": 10, "레전더리": 4}
```

---

### 4.9 시간 유틸리티 (core/time_utils.py — 81줄)

모든 시간은 KST (UTC+9) 기준, 기준 시각은 06:00.

| 함수 | 기간 |
|------|------|
| `get_daily_period()` | 오늘 06:00 ~ 현재 |
| `get_weekly_period()` | 목요일 06:00 ~ 목요일 06:00 |
| `get_monthly_period()` | 1일 06:00 ~ 현재 |
| `get_season_period()` | 시즌 시작 ~ 현재 |
| `get_daily_aggregation_period()` | 어제 06:00 ~ 오늘 05:59:59 |

현재 시즌: **천해천** (2026-03-26 시작), 이전 시즌: 중천

---

### 4.10 로거 (core/logger.py — 68줄)

- `logging.getLogger("jongmini")`
- 파일: `logs/{YYYY-MM-DD}.log` (1MB 로테이션, 14일 자동 삭제)
- 콘솔: stdout 출력
- `KSTFormatter`: `[2026-03-26 14:30:25.123] [INFO] [module:42] message`

---

### 4.11 콘텐츠 모더레이션 (core/chat_moderator.py — 319줄, 비활성)

- 채널별 메시지 큐 (최대 20개)
- 1초 간격 워커 틱
- 외부 Lambda API로 배치 모더레이션
- 응답 파싱: 다중 포맷 지원 + JSON 복구 시도
- 현재 `on_message`에서 주석 처리됨

---

## 5. 슬래시 커맨드 상세 (30개)

### 5.1 캐릭터 관리

#### `/등록` (register.py)
- 파라미터: 서버(Choice), 캐릭터명(str)
- 플로우: API 검색 → CharacterSelect UI (드롭다운) → 캐릭터 이미지 Embed (최대 5개) → DB 저장
- 60초 타임아웃, `interaction.response.defer(thinking=True)` 사용

#### `/전체조회` (total.py)
- 모험단별 그룹핑
- PaginationView: ◀/▶ 버튼, 페이지당 10개 Embed

#### `/출력채널` (set_output_channel.py)
- 관리자 전용 (`administrator=True`)
- 아이템 채널 / 경제 채널 독립 설정
- 채널 자동완성

---

### 5.2 현황 조회 (5개)

모두 `aggregate_items_and_notify_for_period()`를 시간 범위만 다르게 호출:

| 커맨드 | 기간 함수 | 특이사항 |
|--------|----------|---------|
| `/오늘현황` | `get_daily_period()` | |
| `/주간현황` | `get_weekly_period()` | |
| `/월간현황` | `get_monthly_period()` | Embed 반환 |
| `/시즌현황` | `get_season_period()` | 시즌명 포함 |
| `/주간캐릭터현황` | `get_weekly_period()` | 캐릭터별 분류 |

---

### 5.3 던담 랭킹 (3개)

#### `/던담순위` (dundam_ranking.py — 228줄)
- 유형: 딜러 / 버퍼 선택
- 실시간 API → 캐시 폴백 패턴
- 페이지네이션 (20개/페이지)
- 점수 포맷: 한국식 (억/만)

#### `/던담검색제외` (dundam_exclusion.py — 164줄)
- AdventureExclusionView: 토글 버튼 (최대 24개, Discord 제한) + 저장 버튼
- ✅(포함) / ❌(제외) 시각 표시

#### `/모험단던담순위` (adventure_dundam_ranking.py — 182줄)
- 모험단별 딜량 합산 랭킹
- 캐릭터 수 표시

---

### 5.4 경매장 시세 (6개)

#### `/시세등록`, `/시세해제`, `/시세목록` (auction_watch.py — 323줄)
- 등록: 아이템 검색 → 거래 가능 필터 → 선택 → 초기 가격 수집
- 해제: 페이지네이션 (25개/페이지) 셀렉트
- 목록: Embed 목록 (아이템 이미지 포함)

#### `/시세차트` (auction_chart.py — 397줄)
- 파라미터: item_name (자동완성)
- **5가지 간격**: 1분, 15분, 1시간, 4시간, 1일
- **4가지 기간**: 1일, 3일, 7일, 30일
- ChartControlView: 9개 버튼 (5 간격 + 4 기간)
- 사용자별 선호도 캐시 (`_user_prefs`)
- 최근 검색 아이템 추적 (DB 저장, 최대 10개)
- 3개 Embed: 차트 + 기술 분석 + 가격 추천

#### `/시세비교` (auction_compare.py — 411줄)
- 2개 아이템 비교 (듀얼 Y축 차트)
- 피어슨 상관계수 + 해석 텍스트
- 동일 아이템 거부, 미등록 아이템 감지

#### `/시세현황` (auction_overview.py — 77줄)
- 24시간 전체 아이템 스파크라인 오버뷰
- 변화율 절대값 기준 정렬

---

### 5.5 시세 알림 (3개)

#### `/시세알림` (alert_settings.py — 446줄)

9가지 알림 유형:

| 유형 | 감지 조건 | 기본값 |
|------|----------|--------|
| surge (급등) | 1시간 변화 ≥ 30% | 30% |
| crash (급락) | 1시간 변화 ≤ -30% | 30% |
| new_high (신고가) | 기간 내 최고 | 7일 |
| new_low (신저가) | 기간 내 최저 | 7일 |
| volume_spike (거래량 폭증) | 배수 기준 | 10x |
| rsi_upper (RSI 과매수) | RSI ≥ threshold | 70 |
| rsi_lower (RSI 과매도) | RSI ≤ threshold | 30 |
| price_above (지정가 이상) | 고정가 이상 | — |
| price_below (지정가 이하) | 고정가 이하 | — |

- AlertTypeView: 9개 버튼 + 리셋
- ThresholdInputModal: 사용자 임계값 입력
- 1회(자동 삭제) / 반복(영구) 모드

---

### 5.6 경제 지표 (2개)

#### `/활동지수` (activity_basket.py 일부)
- 기간: 7~90일 선택
- 해석: ≥110% 활발(빨강), 90~110% 보통(녹색), <90% 저조(파랑)
- Embed 필드: Hampel 통계, PELT 변화점(최근 3개), MAD 이상치(최근 3일)

#### `/던스피` (dunspy.py — 180줄)
- 5개 기간 버튼: 7/14/30/60/90일
- 구성종목 변화율 표시 (🔴/🔵/⚪)
- 현재가, 변화량, 변화율, 고가/저가

---

### 5.7 아바타 마켓 (2개)

#### `/아바타검색` (avatar_search.py — 188줄)
- 17개 직업, 5개 레어리티, 12개 부위 선택
- 해시태그 자동완성
- 페이지네이션 (5개/페이지)

#### `/아바타시세` (avatar_price.py — 148줄)
- 최근 거래 가격 통계 (평균, 최소, 최대, 중앙값)
- 선물/양도 필터링 (≤10G 제외)
- 최근 15건 상세 표시

---

### 5.8 데이터 관리 (2개)

#### `/데이터내보내기` (export_data.py — 346줄)
- Excel(.xlsx) 생성 (openpyxl)
- 시트 구성: 요약 + 아이템별 데이터 시트
- SFTP 업로드 (Ed25519 키 인증, paramiko)
- 셀 스타일링: 헤더(파랑 배경/흰 텍스트), 통화 포맷, 고정 패널

#### `/쉬었음` (rest_days.py — 130줄)
- 시즌 기준 모험단별 미접속 일수 추적
- 현재 연속 미접속, 최대 연속, 마지막 활동일
- 아이콘 코딩: ✅/😴/🏕️/📋

---

## 6. 백그라운드 태스크 상세

### 6.1 실시간 득템 알림 (tasks/notify_items.py)

```
[20초 간격 무한 루프]
    │
    ├── 모든 등록 캐릭터 순회
    │   ├── Semaphore(50) 동시 제한
    │   ├── 마지막 체크 시간 이후 타임라인 조회
    │   ├── 레벨 115+ 에픽/태초 아이템 필터링
    │   ├── 캐릭터명 변경 감지 → DB 동기화
    │   └── 새 아이템만 추출 (시간 비교)
    │
    └── 아이템별 Embed → item 채널 발송
```

- 아이템 코드별 내러티브: 505(던전 드롭), 504(상자 루팅), 507(레이드 보상), 513(카드 보상)
- 인메모리 상태: `last_processed_time {char_id: datetime}` + `asyncio.Lock`
- 미체크 캐릭터: 30분 lookback

### 6.2 일간 집계 (tasks/daily_aggregation.py)

```
[06:00 KST 트리거 / 커맨드에서 직접 호출]
    │
    ├── 기간 > 90일이면 자동 분할
    ├── 캐릭터별 병렬 처리 (Semaphore 50)
    │   ├── 타임라인 가져오기 (7시간 최대 재시도)
    │   └── 아이템 레벨 115 필터링 (Semaphore 50)
    │
    ├── 모험단별 점수 계산
    │   └── score = Σ(rarity_weight × count)
    │
    └── 랭킹 Embed 생성 → 채널 발송 or interaction 응답
```

핵심: `aggregate_items_and_notify_for_period()`는 커맨드(/오늘현황 등)에서도, 백그라운드 태스크에서도 호출되는 공유 함수.

### 6.3 주간/월간 집계

- `weekly_aggregation.py`: 무한 루프, 다음 목요일 06:00까지 대기 후 실행
- `monthly_aggregation.py`: 무한 루프, 다음 1일 06:00까지 대기 후 실행

### 6.4 경매장 시세 폴링 (tasks/poll_auction_prices.py)

```
[30초 간격 무한 루프]
    │
    ├── 모든 시세 감시 아이템 순회
    │   ├── fetch_auction_sold() → 거래 내역 조회
    │   ├── save_auction_prices() → DB 저장
    │   ├── process_alerts_for_item() → 채널 알림 평가
    │   └── process_user_alerts_for_item() → 개인 DM 알림 평가
    │
    └── 아이템별 독립 에러 처리 (하나 실패해도 계속)
```

### 6.5 시세 알림 처리 (tasks/price_alert.py)

**채널 알림 (자동 감지)**:
- 급등/급락: 1시간 변화 ±30%
- Fat-finger: 중앙값 대비 3x 이상 / 60% 이하
- 신고가/신저가: IQR 범위 내 최고/최저

**쿨다운 시스템**:
- 키: `(item_id, event_type)`
- 60분 쿨다운 → 알림 스팸 방지

**기술 지표 상태 추적**:
- `_prev_state[item_id] = {rsi_zone, ma5_above_ma20}`
- RSI 영역 전환, MA 골든/데드 크로스 감지

**사용자 알림**:
- DB의 `user_alert_settings` 기반
- 1회 알림: 발동 후 자동 비활성화
- `bot.get_user().send()` DM 발송

### 6.6 모닝 브리핑 (tasks/morning_briefing.py)

매일 06:00 KST 경제 채널 발송:
- 시장 평균 변화율
- 총 거래량 + 변화량
- 상승/하락/보합 종목 수
- 주요 등락종목
- 골든/데드 크로스 시그널
- 히트맵 차트

---

## 7. 동시성 및 성능 패턴

### 7.1 세마포어 제어

| 위치 | 세마포어 | 한도 | 대상 |
|------|---------|------|------|
| notify_items.py | 캐릭터 타임라인 | 50 | DNF API |
| notify_items.py | 아이템 레벨 조회 | 50 | DNF API |
| daily_aggregation.py | 캐릭터 처리 | 50 | DNF API |
| dundam_api.py | 외부 API | 5 | dundam.xyz |

### 7.2 캐싱 전략

| 레벨 | 대상 | TTL | 메커니즘 |
|------|------|-----|---------|
| 인메모리 | 아이템 상세 | 영구 | `ITEM_DETAIL_MEMCACHE` dict |
| 인메모리 | 던담 데이터 | 10분 | `_cache` dict + 타임스탬프 |
| 인메모리 | 아바타 해시태그 | 1시간 | |
| 인메모리 | 아바타 직업 | 24시간 | |
| 인메모리 | 사용자 선호도 | 세션 | `_user_prefs` dict |
| DB | 아이템 레벨 | 영구 | `item_cache` 테이블 |
| DB | 던담 랭킹 | 수동 갱신 | `dundam_ranking_cache` 테이블 |
| DB | 최근 검색 | 영구 (10개 제한) | `user_recent_items` 테이블 |

### 7.3 재시도 전략

| 위치 | 최대 재시도 | 간격 | 최대 시간 |
|------|-----------|------|----------|
| 일간 집계 타임라인 | 무제한 | 60초 | 7시간 |
| 던담 API | 3회 | 2^n + random | ~10초 |
| 일반 API | 없음 | — | 30초 타임아웃 |

### 7.4 스레드 안전

- `threading.Lock()` — matplotlib 전역 rcParams 보호
- `asyncio.Lock()` — `last_processed_time` 딕셔너리 접근 보호
- `asyncio.Lock()` — ChatModerator 채널별 API 호출 동기화

---

## 8. 알림 채널 구조

```
output_channels 테이블
├── channel_id       ← 기본 채널 (폴백)
├── item_channel_id  ← 아이템 전용 채널
│   ├── 득템 알림 (notify_items)
│   ├── 일간/주간/월간 랭킹 (aggregation)
│   └── 캐릭터별 집계
└── economy_channel_id ← 경제 전용 채널
    ├── 시세 급등/급락 알림 (price_alert)
    ├── 모닝 브리핑 (morning_briefing)
    └── fat-finger / 신고가 / 신저가 알림
```

`get_output_channel(guild_id, "item")` — item_channel_id 우선, 없으면 channel_id 폴백

---

## 9. 데이터 흐름도

### 9.1 득템 알림 흐름

```
캐릭터 등록 (/등록)
    ↓
[20초 간격] periodic_notify()
    ↓
DNF API: /timeline (code=505,504,507,508,513,550,551,552,553,554,555,556)
    ↓
아이템 레벨 필터 (≥115, 에픽/태초)
    ↓ (3-tier 캐시: 메모리 → DB → API)
중복 제거 (last_checked 비교)
    ↓
Discord Embed → item 채널
```

### 9.2 시세 분석 흐름

```
시세 등록 (/시세등록)
    ↓
[30초 간격] poll_auction_prices()
    ↓
DNF API: /auction-sold (limit=400)
    ↓
auction_price_history 테이블 (INSERT OR IGNORE)
    ↓
price_alert 평가 → 채널/DM 알림
    ↓
/시세차트 요청 시:
    ↓
OHLC 집계 (IQR 필터 → 리샘플링)
    ↓
캔들스틱 차트 + RSI/MA 분석 + 가격 추천
    ↓
Discord Embed + PNG 첨부
```

### 9.3 활동지수 흐름

```
바스켓 등록 (/바스켓등록)
    ↓
/활동지수 요청
    ↓
DB: daily_avg_prices (바스켓 아이템별)
    ↓
[Hampel] 스파이크 제거
    ↓
[STL] 요일 효과 제거
    ↓
[PELT] 체제 전환 감지
    ↓
체제별 30일 MA 정규화
    ↓
일별 중앙값 → 활동지수
    ↓
[MAD] 이상치 마커 (표시용)
    ↓
활동지수 차트 + Embed
```

---

## 10. CI/CD 및 배포

### 10.1 브랜치 전략

```
feature/* → PR → master (개발) → merge → release/latest (프로덕션)
```

### 10.2 Docker 빌드

```dockerfile
FROM python:3.11
RUN apt-get install fonts-nanum     # 한글 폰트
COPY . .
RUN pip install -r requirements.txt
RUN python setup_sftp_auth.py build_ext --inplace  # _sftp_auth.py → .so
RUN rm -f core/_sftp_auth.py core/_sftp_auth.c     # 소스 삭제 (보안)
CMD ["python", "main.py"]
```

### 10.3 CI/CD 파이프라인

CLAUDE.md에 기술된 워크플로우 (`.github/workflows/docker-publish.yml`):
1. `release/latest` push 시 자동 실행
2. Docker 이미지 빌드 → Docker Hub push (`kangjongwoo333/jongmini-bot:latest`)
3. Portainer API로 컨테이너 자동 재생성 (20초 대기 후 recreate)

> 참고: `.github/workflows/` 디렉토리는 현재 로컬에 없음 (아마 release/latest 브랜치에만 존재하거나 별도 관리)

---

## 11. 테스트

### 11.1 테스트 구성

- 프레임워크: pytest (asyncio_mode=auto)
- 테스트 파일: 8개 (+ conftest.py + __init__.py)

| 테스트 파일 | 대상 모듈 |
|------------|----------|
| test_analysis.py | 기술 분석 (RSI, MA, 상관관계) |
| test_chart.py | 차트 생성 |
| test_db.py | 데이터베이스 CRUD |
| test_dnf_api.py | DNF API 호출 |
| test_dundam_api.py | 던담 API |
| test_morning_briefing.py | 모닝 브리핑 |
| test_price_alert.py | 시세 알림 |
| test_time_utils.py | 시간 유틸리티 |

### 11.2 테스트 Fixture (conftest.py)

- `event_loop`: 세션 스코프 이벤트 루프
- `test_db`: 임시 SQLite DB (tmp_path 사용, DB_PATH 패치)
- `sample_price_records`: 100개 가격 기록 (시간별, 변동 시뮬레이션)
- `sample_ohlc_df`: 30캔들 상승 추세 OHLC
- `sample_ohlc_bearish`: 30캔들 하락 추세 OHLC

---

## 12. 외부 의존성

### 12.1 Python 패키지 (18개)

| 패키지 | 버전 | 용도 |
|--------|------|------|
| discord.py | 2.5.2 | 디스코드 봇 프레임워크 |
| aiohttp | ~3.12 | 비동기 HTTP 클라이언트 |
| aiosqlite | ~0.21 | 비동기 SQLite |
| APScheduler | ~3.11 | 정기 작업 스케줄링 |
| matplotlib | ~3.9 | 차트 렌더링 |
| mplfinance | ~0.12.10b0 | 캔들스틱 차트 |
| pandas | ~2.2 | 데이터프레임 처리 |
| numpy | ~1.26 | 수치 연산 |
| statsmodels | ~0.14 | STL 분해 |
| ruptures | ~1.1.9 | PELT 변화점 탐지 |
| paramiko | ~3.5 | SFTP 업로드 |
| openpyxl | ~3.1 | Excel 생성 |
| requests | 2.32.4 | 동기 HTTP (데모용) |
| python-dotenv | 1.1.0 | 환경변수 로딩 |
| pytz | ~2025.2 | 타임존 (zoneinfo 폴백) |

### 12.2 외부 API

| API | 용도 | 인증 | 제한 |
|-----|------|------|------|
| 네오플 DNF API | 캐릭터/타임라인/경매장 | API Key | 초당 제한 미상 |
| dundam.xyz | 딜량 랭킹 | 없음 | 일 20,000건 |
| 모더레이션 Lambda | 채팅 모더레이션 | API Key | (비활성) |

---

## 13. 설계 특징 및 관찰

### 13.1 강점

1. **견고한 비동기 아키텍처**: 세마포어 기반 동시성 제어, 재시도 로직, 독립적 에러 처리
2. **3-tier 캐싱**: 메모리 → DB → API 계층으로 API 호출 최소화
3. **고급 통계 분석**: Hampel + STL + PELT 파이프라인은 학술적 수준의 시계열 분석
4. **체제별 정규화**: 시즌 업데이트 시 기준선 자동 조정
5. **하위 호환 채널 시스템**: 타입별 채널 미설정 시 기존 채널로 폴백
6. **쿨다운 기반 알림**: 스팸 방지 + 의미 있는 이벤트만 전달
7. **사용자 경험**: 자동완성, 최근 검색 추적, 선호도 기억
8. **보안**: SFTP 인증 코드 Cython 컴파일 후 소스 삭제

### 13.2 아키텍처 결정

- **SQLite 선택**: 단일 인스턴스 봇에 적합, WAL 모드로 읽기 동시성 확보
- **길드별 sync**: 글로벌 sync의 1시간 지연 없이 즉시 반영
- **IQR 3.0 기준**: 보수적 이상치 필터링 (정규분포에서 ~4.4σ에 해당)
- **중앙값 집계**: 평균 대비 극단값에 강건한 지표 산출
- **30초 폴링**: 경매장 데이터 갱신 주기와 API 부하 간 균형

### 13.3 비활성 기능

- `ChatModerator`: `on_message()`에서 주석 처리
- `weekly_character_aggregation`: main.py에서 import 주석 처리
- APScheduler의 캐릭터별 주간 집계 CronTrigger: 주석 처리

---

## 14. 환경 변수

| 변수 | 필수 | 용도 |
|------|------|------|
| `DISCORD_TOKEN` | Y | 봇 인증 토큰 |
| `NEOPLE_API_KEY` | Y | DNF API 키 |
| `GUILD_ID` | Y | 기본 길드 ID |
| `DUNDAM_DAILY_LIMIT` | N | 일일 API 한도 (기본 20,000) |
| `MODERATE_ENDPOINT` | N | 모더레이션 API URL |
| `MODERATE_API_KEY` | N | 모더레이션 API 키 |
| `MODERATE_KEY_NAME` | N | 모더레이션 헤더 키명 |
| `SFTP_HOST` | N | 데이터 내보내기 SFTP 호스트 |
| `SFTP_USER` | N | SFTP 사용자 |
| `SFTP_PORT` | N | SFTP 포트 |
| `SFTP_KEY_DATA` | N | SFTP Ed25519 키 데이터 |
| `SFTP_EXPORT_PATH` | N | SFTP 업로드 경로 |

---

## 15. 코드 규모 요약

| 디렉토리 | 파일 수 | 추정 라인 수 |
|----------|--------|-------------|
| core/ | 14 | ~4,500 |
| commands/ | 22 | ~4,000 |
| tasks/ | 8 | ~1,500 |
| tests/ | 10 | ~800 |
| main.py | 1 | 227 |
| **합계** | **55** | **~11,000** |

---

## 16. 문서

- `CLAUDE.md`: 프로젝트 종합 가이드 (아키텍처, 커맨드 목록, DB 스키마, 컨벤션, CI/CD)
- `docs/activity_index_algorithm.md`: 활동지수 노이즈 감소 파이프라인 상세 설명 (316줄)
- `docs/dnf_api_reference.md`: DNF API 엔드포인트 레퍼런스
- `docs/api_responses/`: 35개 API 응답 샘플 JSON (개발/디버깅용)

---

*이 보고서는 프로젝트의 모든 파일을 직접 읽고 분석하여 작성되었습니다.*
