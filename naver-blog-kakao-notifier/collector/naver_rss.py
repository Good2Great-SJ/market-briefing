import re
from datetime import datetime, timezone

import feedparser
import requests
from bs4 import BeautifulSoup

from db.db import insert_post, post_exists

RSS_URL_TEMPLATE = "https://rss.blog.naver.com/{blog_id}.xml"
MOBILE_POST_URL_TEMPLATE = "https://m.blog.naver.com/{blog_id}/{log_no}"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) naver-blog-kakao-notifier"}

LOG_NO_PATTERN = re.compile(r"/(\d+)(?:$|\?)")


def _extract_log_no(link: str) -> str | None:
    match = LOG_NO_PATTERN.search(link)
    return match.group(1) if match else None


def _to_iso8601(published_parsed) -> str:
    if not published_parsed:
        return datetime.now(timezone.utc).isoformat()
    return datetime(*published_parsed[:6], tzinfo=timezone.utc).isoformat()


def _fetch_content(blog_id: str, log_no: str) -> str:
    url = MOBILE_POST_URL_TEMPLATE.format(blog_id=blog_id, log_no=log_no)
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    content_el = soup.select_one(".se-main-container") or soup.select_one("#postViewArea")
    if content_el is None:
        return ""
    return content_el.get_text(separator="\n", strip=True)


def fetch_new_posts(blog_id: str) -> list[dict]:
    """RSS에서 신규 글을 조회하고, 중복 필터링 후 DB에 status='collected'로 저장한다."""
    feed = feedparser.parse(RSS_URL_TEMPLATE.format(blog_id=blog_id), request_headers=HEADERS)
    new_posts = []

    for entry in feed.entries:
        log_no = _extract_log_no(entry.link)
        if not log_no:
            continue

        post_id = f"{blog_id}_{log_no}"
        if post_exists(post_id):
            continue

        post = {
            "post_id": post_id,
            "blog_id": blog_id,
            "title": entry.title,
            "url": entry.link,
            "published_at": _to_iso8601(entry.get("published_parsed")),
            "raw_content": _fetch_content(blog_id, log_no),
        }
        insert_post(post)
        new_posts.append(post)

    return new_posts
