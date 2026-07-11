import json
import os
from datetime import datetime, timezone

import requests
import yaml
from dotenv import load_dotenv

from auth.kakao_auth import refresh_access_token
from db.db import get_kakao_tokens, update_post_status

load_dotenv()

SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")

MESSAGE_TEMPLATE = """\
🆕 [{source_name}] {label} 알림

📌 {title}

{summary}

{keywords_line}
🔗 {url}"""


def _load_source_map() -> dict:
    """config.yaml의 blogs/youtube_channels 목록에서 {source_id: {name, type}} 매핑을 만든다."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    source_map = {}
    for blog in cfg.get("blogs") or []:
        source_map[blog["blog_id"]] = {"name": blog.get("name", blog["blog_id"]), "type": "blog"}
    for channel in cfg.get("youtube_channels") or []:
        source_map[channel["channel_id"]] = {"name": channel.get("name", channel["channel_id"]), "type": "youtube"}
    return source_map


def _format_summary(summary: str) -> str:
    """불릿 포인트 사이에 빈 줄을 넣어 카카오톡에서 가독성 있게 표시한다."""
    lines = [line.strip() for line in summary.split("\n") if line.strip()]
    return "\n\n".join(lines)


def _build_template(post: dict) -> dict:
    source = _load_source_map().get(post["blog_id"], {"name": post["blog_id"], "type": "blog"})
    label = "새로운 영상" if source["type"] == "youtube" else "새로운 글"

    keywords = [k.strip() for k in post.get("keywords", "").split(",") if k.strip()]
    keywords_line = " ".join(f"#{k}" for k in keywords) if keywords else ""

    text = MESSAGE_TEMPLATE.format(
        source_name=source["name"],
        label=label,
        title=post["title"],
        summary=_format_summary(post.get("summary", "")),
        keywords_line=keywords_line,
        url=post["url"],
    )
    return {
        "object_type": "text",
        "text": text,
        "link": {
            "web_url": post["url"],
            "mobile_web_url": post["url"],
        },
        "button_title": "원문 보기" if source["type"] == "blog" else "영상 보기",
    }


def _send(access_token: str, template_object: dict) -> requests.Response:
    return requests.post(
        SEND_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": json.dumps(template_object, ensure_ascii=False)},
        timeout=10,
    )


def send_notification(post: dict) -> dict:
    """post를 카카오톡 '나에게 보내기'로 발송하고, 성공 시 status='notified'로 갱신한다."""
    tokens = get_kakao_tokens()
    if not tokens:
        raise RuntimeError("카카오 토큰이 없습니다. auth/kakao_auth.py로 먼저 인증하세요.")

    template_object = _build_template(post)
    resp = _send(tokens["access_token"], template_object)

    if resp.status_code == 401:
        tokens = refresh_access_token()
        resp = _send(tokens["access_token"], template_object)

    resp.raise_for_status()

    update_post_status(
        post["post_id"], "notified", notified_at=datetime.now(timezone.utc).isoformat()
    )
    return resp.json()
