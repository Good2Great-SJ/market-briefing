from datetime import datetime, timezone

import feedparser
from youtube_transcript_api import NoTranscriptFound, TranscriptsDisabled, YouTubeTranscriptApi

from db.db import insert_post, post_exists

RSS_URL_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) naver-blog-kakao-notifier"}

_transcript_api = YouTubeTranscriptApi()


def _to_iso8601(published_parsed) -> str:
    if not published_parsed:
        return datetime.now(timezone.utc).isoformat()
    return datetime(*published_parsed[:6], tzinfo=timezone.utc).isoformat()


def _fetch_transcript(video_id: str) -> str:
    try:
        transcript = _transcript_api.fetch(video_id, languages=["ko", "en"])
    except (TranscriptsDisabled, NoTranscriptFound):
        return ""
    return "\n".join(segment.text for segment in transcript)


def fetch_new_videos(channel_id: str, fetch_transcript: bool = True) -> list[dict]:
    """채널 RSS에서 신규 영상을 조회하고, 중복 필터링 후 DB에 저장한다.

    fetch_transcript=False면 자막 조회를 건너뛴다 (기준선/백로그 처리용).
    자막이 없는 영상은 요약할 소재가 없으므로 status='summarize_failed'로 즉시 처리한다.
    """
    feed = feedparser.parse(RSS_URL_TEMPLATE.format(channel_id=channel_id), request_headers=HEADERS)
    new_videos = []

    for entry in feed.entries:
        video_id = entry.get("yt_videoid")
        if not video_id:
            continue

        if "/shorts/" in entry.link:
            continue

        post_id = f"{channel_id}_{video_id}"
        if post_exists(post_id):
            continue

        transcript = _fetch_transcript(video_id) if fetch_transcript else ""

        video = {
            "post_id": post_id,
            "blog_id": channel_id,
            "title": entry.title,
            "url": entry.link,
            "published_at": _to_iso8601(entry.get("published_parsed")),
            "raw_content": transcript,
        }
        if fetch_transcript and not transcript:
            video["status"] = "summarize_failed"

        insert_post(video)
        new_videos.append(video)

    return new_videos
