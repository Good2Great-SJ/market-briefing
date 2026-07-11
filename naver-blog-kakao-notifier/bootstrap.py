import os
from datetime import datetime, timezone

import yaml

from collector.naver_rss import fetch_new_posts
from collector.youtube_rss import fetch_new_videos
from db.db import init_db, update_post_status

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")


def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def bootstrap():
    """모든 블로그의 기존 글을 기준선으로 수집만 하고, 요약/알림 없이 notified 처리한다.
    최초 실행 시 과거 글이 전부 '신규 글'로 인식되어 대량 요약/알림이 발생하는 것을 방지한다."""
    init_db()
    cfg = _load_config()
    now = datetime.now(timezone.utc).isoformat()

    total = 0
    for blog in cfg.get("blogs") or []:
        blog_id = blog["blog_id"]
        new_posts = fetch_new_posts(blog_id, fetch_content=False)
        for post in new_posts:
            update_post_status(
                post["post_id"], "notified", notified_at=now, summary="(기준선 설정 - 요약 생략)"
            )
        print(f"{blog_id}: {len(new_posts)}건 기준선 처리")
        total += len(new_posts)

    for channel in cfg.get("youtube_channels") or []:
        channel_id = channel["channel_id"]
        new_videos = fetch_new_videos(channel_id, fetch_transcript=False)
        for video in new_videos:
            update_post_status(
                video["post_id"], "notified", notified_at=now, summary="(기준선 설정 - 요약 생략)"
            )
        print(f"{channel_id}: {len(new_videos)}건 기준선 처리")
        total += len(new_videos)

    print(f"기준선 설정 완료, 총 {total}건")


if __name__ == "__main__":
    bootstrap()
