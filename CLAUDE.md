# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

종미니 봇(Jongmini Bot) - 던전앤파이터(DNF) 오픈 API를 활용한 실시간 득템 알림 및 경매장 시세 분석 디스코드 봇.
Python 3.11+, discord.py 2.x 기반의 완전 비동기(async/await) 아키텍처.

## Commands

```bash
# 봇 실행
python main.py

# 린트
flake8

# 의존성 설치
pip install -r requirements.txt
```

자동화된 테스트 스위트는 없음. `dnf_api_demo.py`, `dnf_api_timeline_demo.py` 등 수동 데모 스크립트로 API 동작 확인.

## Architecture

### 모듈 구조

- **`main.py`**: 진입점. `JongminiBot` 클래스 정의, 슬래시 커맨드 등록, `APScheduler` 스케줄링, 백그라운드 태스크 시작
- **`commands/`**: 디스코드 슬래시 커맨드. 각 파일이 하나의 `@app_commands.command` 함수를 export
- **`core/`**: 핵심 비즈니스 로직
  - `db.py` - aiosqlite 기반 SQLite 데이터 접근 계층 (DB 파일: `data/characters.db`)
  - `dnf_api.py` - 네오플 DNF API 래퍼 (aiohttp, 세마포어 기반 동시성 제어)
  - `dundam_api.py` - 던담 외부 랭킹 API
  - `chart.py` - matplotlib/mplfinance 기반 캔들스틱, 스파크라인, 오버뷰 차트 생성
  - `analysis.py` - 통계 분석 (IQR 이상치 필터링, Hampel 필터 등)
  - `activity_index.py` - 활동지수 계산 (바스켓 기반 거래량 가중 평균)
  - `dunspy_index.py` - 던스피(DUNSPY) 종합지수 산출
  - `models.py` - 서버 매핑, 희귀도 가중치 등 상수
  - `time_utils.py` - KST 기준 기간 계산 유틸리티
  - `chat_moderator.py` - 콘텐츠 모더레이션 (현재 비활성)
  - `logger.py` - 로깅 설정 (1MB 로테이션, 14일 보존)
- **`tasks/`**: 백그라운드 태스크 (asyncio.create_task로 실행)
  - `notify_items.py` - 20초 간격 타임라인 모니터링 및 득템 알림 → **아이템 채널**
  - `daily/weekly/monthly_aggregation.py` - 정기 통계 집계 (KST 06:00 기준) → **아이템 채널**
  - `poll_auction_prices.py` - 5분 간격 경매장 시세 폴링
  - `price_alert.py` - 시세 급등/급락 감지 및 채널/DM 알림 → **경제 채널**
  - `morning_briefing.py` - 매일 06:00 경제 브리핑 발송 → **경제 채널**
  - `weekly_character_aggregation.py` - 캐릭터별 주간 아이템 집계 → **아이템 채널**

### 슬래시 커맨드 전체 목록

| 카테고리 | 커맨드 | 설명 | 파일 |
|---------|--------|------|------|
| 일반 | `/hello` | 봇 인사 | `hello.py` |
| 캐릭터 | `/등록` | DNF 캐릭터 등록 | `register.py` |
| 캐릭터 | `/전체조회` | 등록 캐릭터 모험단별 조회 | `total.py` |
| 현황 | `/오늘현황` | 일간 아이템 획득량 | `today_status.py` |
| 현황 | `/주간현황` | 주간 아이템 획득량 | `weekly_status.py` |
| 현황 | `/주간캐릭터현황` | 캐릭터별 주간 획득량 | `weekly_character_status.py` |
| 현황 | `/월간현황` | 월간 아이템 획득량 | `monthly_status.py` |
| 현황 | `/시즌현황` | 시즌 아이템 획득량 | `season_status.py` |
| 던담 | `/던담순위` | 전체 캐릭터 던담 랭킹 | `dundam_ranking.py` |
| 던담 | `/모험단던담순위` | 모험단별 던담 합산 순위 | `adventure_dundam_ranking.py` |
| 던담 | `/던담검색제외` | 던담순위 검색 모험단 필터 | `dundam_exclusion.py` |
| 시세 | `/시세등록` | 경매장 시세 추적 아이템 등록 | `auction_watch.py` |
| 시세 | `/시세해제` | 시세 추적 해제 | `auction_watch.py` |
| 시세 | `/시세목록` | 추적 중인 아이템 목록 | `auction_watch.py` |
| 시세 | `/시세차트` | 캔들스틱 차트 조회 | `auction_chart.py` |
| 시세 | `/시세비교` | 아이템 간 시세 비교 차트 | `auction_compare.py` |
| 시세 | `/시세현황` | 24시간 시세 변동 요약 | `auction_overview.py` |
| 시세알림 | `/시세알림` | 개인 DM 시세 알림 설정 | `alert_settings.py` |
| 시세알림 | `/시세알림목록` | 내 시세 알림 목록 | `alert_settings.py` |
| 시세알림 | `/시세알림해제` | 시세 알림 해제 | `alert_settings.py` |
| 활동지수 | `/바스켓등록` | 활동지수 바스켓 아이템 등록 | `activity_basket.py` |
| 활동지수 | `/바스켓해제` | 바스켓 아이템 해제 | `activity_basket.py` |
| 활동지수 | `/바스켓목록` | 바스켓 아이템 목록 | `activity_basket.py` |
| 활동지수 | `/활동지수` | 활동지수 차트 조회 | `activity_basket.py` |
| 활동지수 | `/던스피` | DUNSPY 종합지수 차트 | `dunspy.py` |
| 설정 | `/출력채널` | 아이템/경제 알림 출력 채널 분리 설정 | `set_output_channel.py` |

### 알림 채널 구조

`output_channels` 테이블에서 아이템/경제 알림을 별도 채널로 분리 설정 가능:
- **아이템 채널** (`item_channel_id`): 득템 알림, 일간/주간/월간 랭킹
- **경제 채널** (`economy_channel_id`): 시세 급등/급락 알림, 모닝 브리핑
- 타입별 채널 미설정 시 기존 `channel_id`로 폴백 (하위 호환)

### 핵심 패턴

- **비동기 세마포어**: `dnf_api.py`에서 동시 API 요청 수 제한 (캐릭터 50, 아이템 50)
- **기간 분할**: 90일 초과 기간은 자동으로 분할하여 API 호출
- **인메모리 캐시**: `ITEM_DETAIL_MEMCACHE` (아이템 상세), 던담 API (10분 캐시)
- **커맨드 등록**: `setup_hook()`에서 `tree.add_command()` 등록, `on_ready()`에서 길드별 즉시 sync
- **커맨드 동기화**: 글로벌 sync 대신 길드별 sync로 배포 시 즉시 반영 (추방/재초대 불필요)
- **스케줄링**: APScheduler는 KST 타임존 고정. 봇 부팅 시 미실행 집계 감지 후 즉시 실행
- **IQR 이상치 필터링**: 차트 스케일 왜곡 및 허위 신고가 알림 방지

## DB 테이블

| 테이블 | 용도 |
|--------|------|
| `characters` | 등록된 DNF 캐릭터 정보 |
| `registrations` | 사용자-캐릭터 매핑 |
| `item_cache` | 아이템 장착 레벨 캐시 |
| `output_channels` | 길드별 출력 채널 설정 (아이템/경제 분리) |
| `character_last_checked` | 캐릭터별 마지막 타임라인 체크 시간 |
| `daily_aggregation_log` | 일간 집계 실행 이력 |
| `adventure_exclusions` | 모험단 검색 제외 설정 |
| `auction_watch_items` | 경매장 시세 감시 아이템 |
| `auction_price_history` | 경매장 거래 가격 이력 |
| `user_alert_settings` | 사용자별 DM 시세 알림 설정 |
| `activity_basket` | 활동지수 바스켓 아이템 |

## Environment Variables (.env)

- `DISCORD_TOKEN` - 디스코드 봇 토큰
- `NEOPLE_API_KEY` - DNF 오픈 API 키
- `GUILD_ID` - 디스코드 길드 ID
- `MODERATE_ENDPOINT`, `MODERATE_API_KEY`, `MODERATE_KEY_NAME` - 모더레이션 API (선택)

## Git Workflow & 배포

### 브랜치 전략

- **`master`**: 기본 개발 브랜치. 기능 개발/수정은 이슈 등록 후 feature 브랜치에서 작업 -> PR로 master에 merge
- **`release/latest`**: 프로덕션 배포 브랜치. master의 안정적인 커밋을 merge하면 자동 배포 트리거

### 작업 흐름

```
이슈 등록 -> feature 브랜치 생성 -> 작업 -> PR -> master merge -> release/latest merge -> 자동 배포
```

### CI/CD (`.github/workflows/docker-publish.yml`)

`release/latest` 브랜치에 push 시 자동 실행:
1. Docker 이미지 빌드 (`kangjongwoo333/jongmini-bot:latest`)
2. Docker Hub push
3. Portainer API로 컨테이너 자동 재생성 (20초 대기 후 recreate)

### 릴리즈 버전 관리

현재 버전: **v2.8.0**

Semantic Versioning 규칙:
- **MAJOR (x.0.0)**: 대규모 기능 추가, 기존 커맨드명/DB 스키마 변경 등 breaking change
- **MINOR (0.x.0)**: 새 커맨드 추가, 기존 기능 확장 (하위 호환)
- **PATCH (0.0.x)**: 버그 수정, 성능 개선, 문서 업데이트

릴리즈 절차:
1. `release/latest`에서 `release/vX.Y.Z` 브랜치 생성 및 push
2. `gh release create vX.Y.Z --target release/vX.Y.Z` 로 GitHub 릴리즈 + 노트 작성
3. 릴리즈 노트는 카테고리별로 정리 (feat/fix/refactor/docs/infra)

릴리즈 시점 기준:
- **feat 커밋 3개 이상** 누적 시 MINOR 릴리즈 권장
- **breaking change** 발생 시 MAJOR 릴리즈 필수
- 긴급 버그 수정은 즉시 PATCH 릴리즈

## Conventions

- 언어: 한국어 로그 메시지, 한국어 커맨드명 (`/등록`, `/주간현황` 등)
- 린트: flake8, max-line-length=120
- 커밋: conventional commits (`feat:`, `fix:`, `refactor:` 등)
- 타임존: 모든 시간 처리는 KST (Asia/Seoul) 기준
- DB: SQLite 단일 파일 (`data/characters.db`), aiosqlite로 비동기 접근
- 아이템 필터: 장착 레벨 115 이상, 희귀도 에픽/태초만 알림 대상
