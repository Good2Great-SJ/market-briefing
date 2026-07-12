import json
import logging
import urllib.request
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import feedparser
import yt_dlp

from db.db import get_posts_by_status, insert_post, post_exists, update_post_status

RSS_URL_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) naver-blog-kakao-notifier"}

_logger = logging.getLogger("pipeline")

# 링크/해시태그만 있는 설명란은 요약 소재로 보지 않는다.
MIN_DESCRIPTION_LENGTH = 30

# 영상이 막 올라온 직후에는 YouTube 자동 자막이 아직 생성되지 않은 경우가 많다.
# 이 시간 안에는 자막을 계속 재시도하고, 지나면 설명란 기준으로 확정한다.
TRANSCRIPT_RETRY_HOURS = 3

# YouTube의 봇 차단은 주로 웹 클라이언트 경로에 걸리므로, PO Token이 필요 없는
# android_vr 클라이언트로 자막을 요청한다 (클라우드 IP에서도 차단 없이 동작 확인됨).
_YTDLP_OPTS = {
    "skip_download": True,
    "quiet": True,
    "no_warnings": True,
    "ignore_no_formats_error": True,
    "extractor_args": {"youtube": {"player_client": ["android_vr"]}},
}


def _to_iso8601(published_parsed) -> str:
    if not published_parsed:
        return datetime.now(timezone.utc).isoformat()
    return datetime(*published_parsed[:6], tzinfo=timezone.utc).isoformat()


def _video_id_from_url(url: str) -> str:
    return (parse_qs(urlparse(url).query).get("v") or [""])[0]


def _parse_json3_captions(raw: bytes) -> str:
    payload = json.loads(raw)
    parts = []
    for event in payload.get("events", []):
        for seg in event.get("segs") or []:
            text = seg.get("utf8", "")
            if text:
                parts.append(text)
    return "".join(parts)


def _fetch_transcript(video_id: str) -> str:
    """yt-dlp(android_vr 클라이언트)로 자막을 가져온다. 자막이 없거나 실패하면 ""를 반환한다."""
    try:
        with yt_dlp.YoutubeDL(_YTDLP_OPTS) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    except Exception as exc:
        _logger.warning(f"[자막 조회 실패] {video_id}: {exc}")
        return ""

    tracks = info.get("automatic_captions") or {}
    for lang in ("ko", "en"):
        entries = tracks.get(lang)
        if not entries:
            continue
        caption_url = next((e["url"] for e in entries if e.get("ext") == "json3"), None)
        if not caption_url:
            continue
        try:
            with urllib.request.urlopen(caption_url, timeout=15) as resp:
                return _parse_json3_captions(resp.read())
        except Exception as exc:
            _logger.warning(f"[자막 다운로드 실패] {video_id}: {exc}")
            return ""

    return ""


def _usable_description(entry) -> str:
    """영상 설명란에서 링크/해시태그 줄을 걷어내고, 남는 내용이 요약할 만한 분량인지 확인한다."""
    description = entry.get("summary", "") or ""
    content_lines = [
        line
        for line in description.splitlines()
        if line.strip() and not line.strip().startswith("#") and "http" not in line
    ]
    content = "\n".join(content_lines).strip()
    return content if len(content) >= MIN_DESCRIPTION_LENGTH else ""


def fetch_new_videos(
    channel_id: str, fetch_transcript: bool = True, exclude_keywords: list[str] | None = None
) -> list[dict]:
    """채널 RSS에서 신규 영상을 조회하고, 중복 필터링 후 DB에 저장한다.

    fetch_transcript=False면 자막 조회를 건너뛴다 (기준선/백로그 처리용).
    exclude_keywords에 해당하는 문자열이 제목에 포함된 영상은 수집 대상에서 제외한다.
    자막을 못 가져오면(막 올라온 영상이라 자동 자막이 아직 없거나, 자막 자체가 없거나)
    status='transcript_pending'으로 두고 이후 실행에서 자막을 재시도한다
    (retry_pending_transcripts 참고). 그동안 임시로는 설명란을 raw_content로 채워둔다.
    """
    feed = feedparser.parse(RSS_URL_TEMPLATE.format(channel_id=channel_id), request_headers=HEADERS)
    new_videos = []

    for entry in feed.entries:
        video_id = entry.get("yt_videoid")
        if not video_id:
            continue

        if "/shorts/" in entry.link:
            continue

        if exclude_keywords and any(keyword in entry.title for keyword in exclude_keywords):
            continue

        post_id = f"{channel_id}_{video_id}"
        if post_exists(post_id):
            continue

        video = {
            "post_id": post_id,
            "blog_id": channel_id,
            "title": entry.title,
            "url": entry.link,
            "published_at": _to_iso8601(entry.get("published_parsed")),
            "raw_content": "",
        }

        if fetch_transcript:
            transcript = _fetch_transcript(video_id)
            if transcript:
                video["raw_content"] = transcript
            else:
                video["raw_content"] = _usable_description(entry)
                video["status"] = "transcript_pending"

        insert_post(video)
        new_videos.append(video)

    return new_videos


def retry_pending_transcripts() -> None:
    """자막이 아직 준비되지 않아 대기 중이던 영상의 자막을 재시도한다.

    이번에 자막을 가져오면 status='collected'로 승격시켜 정상 요약 흐름을 타게 하고,
    TRANSCRIPT_RETRY_HOURS가 지나도 안 되면 그동안 채워둔 설명란 기준으로 확정한다
    (설명란마저 없으면 summarize_failed로 포기한다).
    """
    for post in get_posts_by_status("transcript_pending"):
        video_id = _video_id_from_url(post["url"])
        transcript = _fetch_transcript(video_id) if video_id else ""

        if transcript:
            update_post_status(post["post_id"], "collected", raw_content=transcript)
            _logger.info(f"[자막 재시도 성공] {post['post_id']}")
            continue

        collected_at = datetime.fromisoformat(post["collected_at"])
        elapsed_hours = (datetime.now(timezone.utc) - collected_at).total_seconds() / 3600
        if elapsed_hours < TRANSCRIPT_RETRY_HOURS:
            continue

        final_status = "collected" if post.get("raw_content") else "summarize_failed"
        update_post_status(post["post_id"], final_status)
        _logger.info(f"[자막 재시도 포기, {final_status}로 확정] {post['post_id']}")
