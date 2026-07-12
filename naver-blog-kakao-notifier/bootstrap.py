import os
import sys
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


def _mark_baseline(post_ids_and_ids: list, now: str) -> int:
    count = 0
    for item in post_ids_and_ids:
        update_post_status(item["post_id"], "notified", notified_at=now, summary="(기준선 설정 - 요약 생략)")
        count += 1
    return count


def bootstrap(only_id: str | None = None):
    """블로그/채널의 기존 글을 기준선으로 수집만 하고, 요약/알림 없이 notified 처리한다.
    최초 실행 시 과거 글이 전부 '신규 글'로 인식되어 대량 요약/알림이 발생하는 것을 방지한다.

    only_id를 지정하면 해당 blog_id/channel_id 하나만 처리한다. 새 소스를 추가할 때는
    반드시 only_id로 그 소스만 지정해야 한다 — 인자 없이 전체를 재스캔하면, 그 사이 기존
    소스에 올라온 진짜 신규 글이 요약/알림 없이 조용히 기준선 처리(silently swallowed)되는
    문제가 있다 (실제로 한 번 발생했던 이슈).
    """
    init_db()
    cfg = _load_config()
    now = datetime.now(timezone.utc).isoformat()

    total = 0
    for blog in cfg.get("blogs") or []:
        blog_id = blog["blog_id"]
        if only_id and blog_id != only_id:
            continue
        new_posts = fetch_new_posts(blog_id, fetch_content=False)
        count = _mark_baseline(new_posts, now)
        print(f"{blog_id}: {count}건 기준선 처리")
        total += count

    for channel in cfg.get("youtube_channels") or []:
        channel_id = channel["channel_id"]
        if only_id and channel_id != only_id:
            continue
        new_videos = fetch_new_videos(
            channel_id, fetch_transcript=False, exclude_keywords=channel.get("exclude_keywords")
        )
        count = _mark_baseline(new_videos, now)
        print(f"{channel_id}: {count}건 기준선 처리")
        total += count

    print(f"기준선 설정 완료, 총 {total}건")


if __name__ == "__main__":
    bootstrap(only_id=sys.argv[1] if len(sys.argv) > 1 else None)
