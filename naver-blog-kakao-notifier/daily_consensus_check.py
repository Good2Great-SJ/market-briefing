import logging
import os
import sys
from datetime import datetime

from auth.kakao_auth import ensure_session
from consensus.pipeline import check_watchlist_daily
from db.db import init_db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")


def _setup_logger() -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, f"consensus_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

    logger = logging.getLogger("consensus")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def main(force: bool = False):
    logger = _setup_logger()
    logger.info("종목 컨센서스 체크 시작")
    init_db()
    ensure_session()

    result = check_watchlist_daily(force=force)

    if result["skipped"]:
        logger.info("오늘 이미 체크를 완료해 스킵합니다.")
        return

    logger.info(
        f"체크 완료 | 신규 백필 {result['bootstrapped']} | 업데이트 발송 {result['updated']}"
    )


if __name__ == "__main__":
    main(force="--force" in sys.argv)
