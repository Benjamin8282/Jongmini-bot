import logging
from pathlib import Path
from datetime import datetime

# ✅ 로그 디렉토리 생성
log_dir = Path("logs")
log_dir.mkdir(parents=True, exist_ok=True)

try:
    # Python 3.9+ 표준 모듈, 리눅스/나스 같은 환경에서 주로 사용
    from zoneinfo import ZoneInfo

    KST = ZoneInfo("Asia/Seoul")
    print("zoneinfo 사용 중")
except (ImportError, ModuleNotFoundError, KeyError):
    # Windows 또는 zoneinfo 미설치/미지원 환경용 fallback
    import pytz

    KST = pytz.timezone("Asia/Seoul")
    print("pytz 사용 중")

# ✅ 날짜별 파일 이름 (예: logs/2025-06-17.log)
log_filename = log_dir / f"{datetime.now(KST).strftime('%Y-%m-%d')}.log"

# ✅ 로그 포맷 설정
log_format = "[%(asctime)s] [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s"
date_format = "%Y-%m-%d %H:%M:%S.%f"


# ✅ Formatter 커스터마이징 (KST 기준으로 시간 찍기)
class KSTFormatter(logging.Formatter):
    def converter(self, timestamp):
        return datetime.fromtimestamp(timestamp, KST)

    def formatTime(self, record, datefmt=None):
        dt = self.converter(record.created)
        if datefmt:
            s = dt.strftime(datefmt)
            # microseconds 6자리 중 앞 3자리만 (밀리초)
            return s[:-3]
        return dt.isoformat()


# ✅ 로거 설정
logger = logging.getLogger("jongmini")
logger.setLevel(logging.DEBUG)

# ✅ 파일 핸들러
file_handler = logging.FileHandler(log_filename, encoding="utf-8")
file_handler.setFormatter(KSTFormatter(fmt=log_format, datefmt=date_format))

# ✅ 콘솔 핸들러
console_handler = logging.StreamHandler()
console_handler.setFormatter(KSTFormatter(fmt=log_format, datefmt=date_format))

# ✅ 핸들러 추가
logger.addHandler(file_handler)
logger.addHandler(console_handler)
