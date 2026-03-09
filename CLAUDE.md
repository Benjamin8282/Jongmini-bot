# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

종미니 봇(Jongmini Bot) - 던전앤파이터(DNF) 오픈 API를 활용한 실시간 득템 알림 디스코드 봇.
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
  - `models.py` - 서버 매핑, 희귀도 가중치 등 상수
  - `time_utils.py` - KST 기준 기간 계산 유틸리티
  - `chat_moderator.py` - 콘텐츠 모더레이션 (현재 비활성)
  - `logger.py` - 로깅 설정 (1MB 로테이션, 14일 보존)
- **`tasks/`**: 백그라운드 태스크 (asyncio.create_task로 실행)
  - `notify_items.py` - 20초 간격 타임라인 모니터링 및 득템 알림
  - `daily/weekly/monthly_aggregation.py` - 정기 통계 집계 (KST 06:00 기준)
  - `poll_auction_prices.py` - 5분 간격 경매장 시세 폴링

### 핵심 패턴

- **비동기 세마포어**: `dnf_api.py`에서 동시 API 요청 수 제한 (캐릭터 50, 아이템 50)
- **기간 분할**: 90일 초과 기간은 자동으로 분할하여 API 호출
- **인메모리 캐시**: `ITEM_DETAIL_MEMCACHE` (아이템 상세), 던담 API (10분 캐시)
- **커맨드 등록**: `setup_hook()`에서 `self.tree.add_command()`로 등록 후 `tree.sync()`
- **스케줄링**: APScheduler는 KST 타임존 고정. 봇 부팅 시 미실행 집계 감지 후 즉시 실행

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

### 릴리즈 버전

버전 브랜치(`release/v1.x.x`)로 릴리즈 이력 관리. 현재 v1.3.1까지.

## Conventions

- 언어: 한국어 로그 메시지, 한국어 커맨드명 (`/등록`, `/주간현황` 등)
- 린트: flake8, max-line-length=120
- 커밋: conventional commits (`feat:`, `fix:`, `refactor:` 등)
- 타임존: 모든 시간 처리는 KST (Asia/Seoul) 기준
- DB: SQLite 단일 파일 (`data/characters.db`), aiosqlite로 비동기 접근
- 아이템 필터: 장착 레벨 115 이상, 희귀도 에픽/태초만 알림 대상
