import logging
import os
from datetime import datetime

import yaml

from auth.kakao_auth import ensure_session
from collector.naver_rss import fetch_new_posts
from collector.youtube_rss import fetch_new_videos
from db.db import get_posts_by_status, init_db
from notifier.kakao_notifier import send_notification
from summarizer.summarizer import summarize

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
LOG_DIR = os.path.join(BASE_DIR, "logs")


def _setup_logger() -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

    logger = logging.getLogger("pipeline")
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


def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_pipeline():
    logger = _setup_logger()
    logger.info("파이프라인 시작")
    init_db()
    ensure_session()

    cfg = _load_config()
    blogs = cfg.get("blogs") or []
    youtube_channels = cfg.get("youtube_channels") or []

    collected_count = 0
    summarized_count = 0
    notified_count = 0
    error_count = 0

    for blog in blogs:
        blog_id = blog["blog_id"]
        try:
            new_posts = fetch_new_posts(blog_id)
            collected_count += len(new_posts)
            logger.info(f"[수집] {blog_id}: 신규 {len(new_posts)}건")
        except Exception:
            error_count += 1
            logger.exception(f"[수집 실패] {blog_id}")

    for channel in youtube_channels:
        channel_id = channel["channel_id"]
        try:
            new_videos = fetch_new_videos(channel_id, exclude_keywords=channel.get("exclude_keywords"))
            collected_count += len(new_videos)
            logger.info(f"[수집] {channel_id}: 신규 {len(new_videos)}건")
        except Exception:
            error_count += 1
            logger.exception(f"[수집 실패] {channel_id}")

    for post in get_posts_by_status("collected"):
        try:
            summarize(post)
            summarized_count += 1
            logger.info(f"[요약] {post['post_id']}")
        except Exception:
            error_count += 1
            logger.exception(f"[요약 실패] {post['post_id']}")

    for post in get_posts_by_status("summarized"):
        try:
            send_notification(post)
            notified_count += 1
            logger.info(f"[알림] {post['post_id']}")
        except Exception:
            error_count += 1
            logger.exception(f"[알림 실패] {post['post_id']}")

    logger.info(
        f"파이프라인 종료 | 수집 {collected_count} | 요약 {summarized_count} | "
        f"알림 {notified_count} | 오류 {error_count}"
    )


if __name__ == "__main__":
    run_pipeline()
