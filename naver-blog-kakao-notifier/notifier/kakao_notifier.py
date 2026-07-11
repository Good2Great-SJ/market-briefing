import json
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from auth.kakao_auth import refresh_access_token
from db.db import get_kakao_tokens, update_post_status

load_dotenv()

SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"

MESSAGE_TEMPLATE = """\
📝 [{blog_id}] 신규 글 알림

제목: {title}
요약: {summary}
키워드: {keywords}

원문 보기 ▶ {url}"""


def _build_template(post: dict) -> dict:
    text = MESSAGE_TEMPLATE.format(
        blog_id=post["blog_id"],
        title=post["title"],
        summary=post.get("summary", ""),
        keywords=post.get("keywords", ""),
        url=post["url"],
    )
    return {
        "object_type": "text",
        "text": text,
        "link": {
            "web_url": post["url"],
            "mobile_web_url": post["url"],
        },
        "button_title": "원문 보기",
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
