# 종미니 (Jongmini Bot)

## 프로젝트 개요

**종미니 봇**은 네오플의 던전앤파이터(DNF) 오픈 API를 활용하여 실시간 득템 알림, 경매장 시세 분석, 경제 지표 추적까지 제공하는 디스코드 봇입니다.

단순한 아이템 알림을 넘어, 캔들스틱 차트 기반 시세 분석, IQR 이상치 필터링, 활동지수/던스피 종합지수 등 데이터 분석 기능을 갖추고 있습니다.

## 주요 기능

### 실시간 득템 알림
- 등록된 캐릭터의 타임라인을 20초 간격으로 모니터링
- 장착 레벨 115 이상의 에픽/태초 아이템 획득 시 디스코드 채널 자동 알림
- 다중 캐릭터 관리 및 중복 알림 방지

### 통계 및 랭킹
- **일간/주간/월간/시즌별** 모험단 아이템 획득량 집계 및 순위
- **캐릭터별 주간 집계** 상세 분석
- **던담 랭킹** 조회 및 모험단별 합산 순위
- 동점자 처리, 90일 단위 기간 분할 등 정확한 데이터 처리

### 경매장 시세 분석
- **시세 추적**: 아이템별 경매장 거래 이력 5분 간격 수집
- **캔들스틱 차트**: mplfinance 기반 OHLC 차트 생성
- **시세 비교**: 다수 아이템 시세 비교 차트
- **시세 현황**: 24시간 변동률 한눈에 요약
- **시세 알림**: 급등/급락 감지 시 채널 알림 + 개인 DM 알림 (지정가/변동률/거래량 기준)
- **IQR 이상치 필터링**: 차트 스케일 왜곡 및 허위 신고가 알림 방지

### 경제 지표
- **활동지수**: 바스켓 아이템 기반 거래량 가중 평균 지수
- **던스피(DUNSPY)**: 종합 경제 지수 (Hampel 노이즈 제거, PELT 체제 전환 감지, MAD 이상치 감지)
- **모닝 브리핑**: 매일 06:00 시장 요약 리포트 자동 발송

### 알림 채널 분리
- **아이템 알림 채널**: 실시간 득템, 일간/주간/월간 랭킹
- **경제 알림 채널**: 시세 변동, 모닝 브리핑
- `/출력채널` 커맨드로 길드 채널 목록에서 각각 선택 설정

## 슬래시 커맨드

| 카테고리 | 커맨드 | 설명 |
|---------|--------|------|
| 일반 | `/hello` | 봇 인사 |
| 캐릭터 | `/등록` | DNF 캐릭터 등록 |
| 캐릭터 | `/전체조회` | 등록 캐릭터 모험단별 조회 |
| 현황 | `/오늘현황` | 일간 아이템 획득량 |
| 현황 | `/주간현황` | 주간 아이템 획득량 |
| 현황 | `/주간캐릭터현황` | 캐릭터별 주간 획득량 |
| 현황 | `/월간현황` | 월간 아이템 획득량 |
| 현황 | `/시즌현황` | 시즌 아이템 획득량 |
| 던담 | `/던담순위` | 전체 캐릭터 던담 랭킹 |
| 던담 | `/모험단던담순위` | 모험단별 던담 합산 순위 |
| 던담 | `/던담검색제외` | 던담순위 검색 모험단 필터 |
| 시세 | `/시세등록` | 경매장 시세 추적 아이템 등록 |
| 시세 | `/시세해제` | 시세 추적 해제 |
| 시세 | `/시세목록` | 추적 중인 아이템 목록 |
| 시세 | `/시세차트` | 캔들스틱 차트 조회 |
| 시세 | `/시세비교` | 아이템 간 시세 비교 차트 |
| 시세 | `/시세현황` | 24시간 시세 변동 요약 |
| 시세알림 | `/시세알림` | 개인 DM 시세 알림 설정 |
| 시세알림 | `/시세알림목록` | 내 시세 알림 목록 |
| 시세알림 | `/시세알림해제` | 시세 알림 해제 |
| 활동지수 | `/바스켓등록` | 활동지수 바스켓 아이템 등록 |
| 활동지수 | `/바스켓해제` | 바스켓 아이템 해제 |
| 활동지수 | `/바스켓목록` | 바스켓 아이템 목록 |
| 활동지수 | `/활동지수` | 활동지수 차트 조회 |
| 활동지수 | `/던스피` | DUNSPY 종합지수 차트 |
| 설정 | `/출력채널` | 아이템/경제 알림 출력 채널 분리 설정 |

## 기술 스택

| 분류 | 기술 |
|------|------|
| 언어 | Python 3.11+ |
| 봇 프레임워크 | discord.py 2.x (슬래시 커맨드) |
| 비동기 HTTP | aiohttp |
| 데이터베이스 | SQLite (aiosqlite 비동기 접근) |
| 스케줄러 | APScheduler |
| 차트 | matplotlib, mplfinance |
| 데이터 분석 | pandas, numpy, statsmodels, ruptures |
| 환경 변수 | python-dotenv |
| 컨테이너 | Docker |
| CI/CD | GitHub Actions + Portainer API |

## 프로젝트 구조

```
jongmini-bot/
├── main.py                          # 봇 진입점, 초기화, 태스크 시작
├── requirements.txt                 # Python 의존성
├── Dockerfile                       # Docker 이미지 빌드
├── .github/workflows/
│   └── docker-publish.yml           # CI/CD 파이프라인
├── commands/                        # 슬래시 커맨드
│   ├── hello.py                     # /hello
│   ├── register.py                  # /등록
│   ├── total.py                     # /전체조회
│   ├── set_output_channel.py        # /출력채널 (ChannelSelect UI)
│   ├── today_status.py              # /오늘현황
│   ├── weekly_status.py             # /주간현황
│   ├── weekly_character_status.py   # /주간캐릭터현황
│   ├── monthly_status.py            # /월간현황
│   ├── season_status.py             # /시즌현황
│   ├── dundam_ranking.py            # /던담순위
│   ├── adventure_dundam_ranking.py  # /모험단던담순위
│   ├── dundam_exclusion.py          # /던담검색제외
│   ├── auction_watch.py             # /시세등록, /시세해제, /시세목록
│   ├── auction_chart.py             # /시세차트
│   ├── auction_compare.py           # /시세비교
│   ├── auction_overview.py          # /시세현황
│   ├── alert_settings.py            # /시세알림, /시세알림목록, /시세알림해제
│   ├── activity_basket.py           # /바스켓등록, /바스켓해제, /바스켓목록, /활동지수
│   └── dunspy.py                    # /던스피
├── core/                            # 핵심 비즈니스 로직
│   ├── db.py                        # SQLite 데이터 접근 계층
│   ├── dnf_api.py                   # DNF API 래퍼
│   ├── dundam_api.py                # 던담 외부 랭킹 API
│   ├── chart.py                     # 차트 생성 (캔들스틱, 스파크라인, 오버뷰)
│   ├── analysis.py                  # 통계 분석 (IQR, Hampel 등)
│   ├── activity_index.py            # 활동지수 계산
│   ├── dunspy_index.py              # 던스피 종합지수 산출
│   ├── models.py                    # 서버 매핑, 희귀도 가중치 상수
│   ├── time_utils.py                # KST 기준 기간 계산
│   ├── chat_moderator.py            # 콘텐츠 모더레이션 (비활성)
│   └── logger.py                    # 로깅 (1MB 로테이션, 14일 보존)
├── tasks/                           # 백그라운드 태스크
│   ├── notify_items.py              # 20초 간격 타임라인 모니터링
│   ├── daily_aggregation.py         # 일간 집계 (06:00 KST)
│   ├── weekly_aggregation.py        # 주간 집계 (목요일 06:00)
│   ├── monthly_aggregation.py       # 월간 집계 (1일 06:00)
│   ├── weekly_character_aggregation.py  # 캐릭터별 주간 집계
│   ├── poll_auction_prices.py       # 5분 간격 경매장 시세 폴링
│   ├── price_alert.py               # 시세 급등/급락 감지 및 알림
│   └── morning_briefing.py          # 매일 06:00 경제 브리핑
├── data/
│   └── characters.db                # SQLite DB
└── logs/                            # 운영 로그
```

## 배포

### CI/CD 파이프라인

`release/latest` 브랜치에 push 시 자동 실행:
1. Docker 이미지 빌드 (`kangjongwoo333/jongmini-bot:latest`)
2. Docker Hub push
3. Portainer API로 컨테이너 자동 재생성

### 브랜치 전략

```
feature 브랜치 → master (개발) → release/latest (프로덕션 자동 배포)
```

### 커맨드 동기화

길드별 즉시 sync 방식을 사용하여 배포 시 슬래시 커맨드가 즉시 반영됩니다. (글로벌 sync의 최대 1시간 지연 없음)

## 개발자

**강종우**
- Android Native(JAVA, Kotlin) & Python Developer
- [GitHub](https://github.com/Benjamin8282)
- Email: kangjongwoo333@gmail.com
