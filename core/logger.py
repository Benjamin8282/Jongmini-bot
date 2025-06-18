import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
    print("zoneinfo 사용 중")
except (ImportError, ModuleNotFoundError, KeyError):
    import pytz
    KST = pytz.timezone("Asia/Seoul")
    print("pytz 사용 중")

log_dir = Path("logs")
log_dir.mkdir(parents=True, exist_ok=True)

def delete_old_logs(log_directory: Path, days: int = 14):
    cutoff_date = datetime.now(KST) - timedelta(days=days)
    for log_file in log_directory.glob("*.log*"):
        try:
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime, KST)
            if mtime < cutoff_date:
                log_file.unlink()
                print(f"오래된 로그 파일 삭제: {log_file.name}")
        except Exception as e:
            print(f"파일 삭제 중 오류 발생 {log_file}: {e}")

delete_old_logs(log_dir, days=14)

log_filename = log_dir / f"{datetime.now(KST).strftime('%Y-%m-%d')}.log"

log_format = "[%(asctime)s] [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s"
date_format = "%Y-%m-%d %H:%M:%S.%f"

class KSTFormatter(logging.Formatter):
    @staticmethod
    def converter(timestamp):
        return datetime.fromtimestamp(timestamp, KST)

    def formatTime(self, record, datefmt=None):
        dt = self.converter(record.created)
        if datefmt:
            s = dt.strftime(datefmt)
            return s[:-3]
        return dt.isoformat()

logger = logging.getLogger("jongmini")
logger.setLevel(logging.DEBUG)

file_handler = RotatingFileHandler(
    filename=log_filename,
    maxBytes=1 * 1024 * 1024,  # 1MB
    backupCount=0,             # 백업 파일 개수 제한 없음 (0으로 설정하면 기본값 무시)
    encoding="utf-8"
)
file_handler.setFormatter(KSTFormatter(fmt=log_format, datefmt=date_format))

console_handler = logging.StreamHandler()
console_handler.setFormatter(KSTFormatter(fmt=log_format, datefmt=date_format))

logger.addHandler(file_handler)
logger.addHandler(console_handler)
