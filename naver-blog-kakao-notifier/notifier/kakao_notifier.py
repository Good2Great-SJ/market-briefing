import json
import os
import re
from datetime import datetime, timezone
from typing import Callable

import requests
import yaml
from dotenv import load_dotenv

from auth.kakao_auth import refresh_access_token
from db.db import get_kakao_tokens, update_post_status

load_dotenv()

SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")

# 카카오톡 "나에게 보내기" text 템플릿은 약 1000자에서 잘리는 것이 실측으로 확인됨.
# 링크(URL)는 항상 끝까지 보여야 하므로, 넘칠 경우 요약을 불릿 단위로 잘라 안전 마진을 둔다.
MAX_TEXT_LENGTH = 910

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


def _split_bullets(summary: str) -> list[str]:
    return [line.strip() for line in summary.split("\n") if line.strip()]


def _truncate_to_sentence(bullet: str, budget: int) -> str:
    """불릿 하나조차 예산을 초과하는 극단적인 경우, 문장 경계에서 잘라낸다."""
    if len(bullet) <= budget:
        return bullet

    sentences = re.split(r"(?<=[.!?])\s+", bullet)
    included = ""
    for sentence in sentences:
        candidate = f"{included} {sentence}".strip() if included else sentence
        if len(candidate) > budget:
            break
        included = candidate

    if included:
        return included
    # 문장 경계도 못 찾으면 어절 단위로 잘라 말줄임표를 붙인다.
    return bullet[: max(budget - 1, 0)].rsplit(" ", 1)[0] + "…"


def _fit_summary(bullets: list[str], build_text: Callable[[str], str]) -> str:
    """전체 메시지가 MAX_TEXT_LENGTH를 넘지 않는 선에서, 완전한 불릿 단위로만 요약을 구성한다."""
    included: list[str] = []
    for bullet in bullets:
        candidate_summary = "\n\n".join([*included, bullet])
        if len(build_text(candidate_summary)) <= MAX_TEXT_LENGTH:
            included.append(bullet)
        else:
            break

    if included:
        return "\n\n".join(included)

    # 첫 불릿 하나조차 안 들어가는 경우: 그 불릿을 문장 단위로 잘라낸다.
    overhead = len(build_text(""))
    budget = max(MAX_TEXT_LENGTH - overhead, 0)
    return _truncate_to_sentence(bullets[0], budget) if bullets else ""


def _build_template(post: dict) -> dict:
    source = _load_source_map().get(post["blog_id"], {"name": post["blog_id"], "type": "blog"})
    label = "새로운 영상" if source["type"] == "youtube" else "새로운 글"

    keywords = [k.strip() for k in post.get("keywords", "").split(",") if k.strip()]
    keywords_line = " ".join(f"#{k}" for k in keywords) if keywords else ""

    def build_text(summary: str) -> str:
        return MESSAGE_TEMPLATE.format(
            source_name=source["name"],
            label=label,
            title=post["title"],
            summary=summary,
            keywords_line=keywords_line,
            url=post["url"],
        )

    bullets = _split_bullets(post.get("summary", ""))
    fitted_summary = _fit_summary(bullets, build_text)
    text = build_text(fitted_summary)

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


def send_text_message(text: str, link_url: str, button_title: str = "자세히 보기") -> dict:
    """임의의 텍스트를 카카오톡 '나에게 보내기'로 발송한다 (컨센서스 리포트 등 post 기반이 아닌 메시지용)."""
    if len(text) > MAX_TEXT_LENGTH:
        text = text[: MAX_TEXT_LENGTH - 1] + "…"

    template_object = {
        "object_type": "text",
        "text": text,
        "link": {"web_url": link_url, "mobile_web_url": link_url},
        "button_title": button_title,
    }

    tokens = get_kakao_tokens()
    if not tokens:
        raise RuntimeError("카카오 토큰이 없습니다. auth/kakao_auth.py로 먼저 인증하세요.")

    resp = _send(tokens["access_token"], template_object)
    if resp.status_code == 401:
        tokens = refresh_access_token()
        resp = _send(tokens["access_token"], template_object)

    resp.raise_for_status()
    return resp.json()


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
