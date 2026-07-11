import json
import os

import yaml
from anthropic import Anthropic
from dotenv import load_dotenv

from db.db import update_post_status

load_dotenv()

PROMPT_TEMPLATE = """\
다음 글을 한국어로 요약하고, 핵심 키워드 3개를 뽑아줘.
요약은 카카오톡 메시지로 발송될 것이므로 가독성이 중요해:
- 2~4개의 핵심 포인트로 나눠서 각각 "• "로 시작하는 한두 문장으로 작성
- 포인트 사이는 줄바꿈(\\n)으로 구분
- 각 포인트는 핵심 내용과 맥락이 충분히 전달되도록 하되, 불필요하게 늘리지는 마

반드시 아래 JSON 형식으로만 응답 (summary 안의 줄바꿈은 \\n으로 이스케이프):
{{
  "summary": "• 첫 번째 포인트\\n• 두 번째 포인트\\n• 세 번째 포인트",
  "keywords": ["...", "...", "..."]
}}

[본문]
{raw_content}
"""


def _load_summarizer_config() -> dict:
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg["summarizer"]


def _call_claude(client: Anthropic, model: str, raw_content: str, max_content_length: int) -> dict:
    truncated = raw_content[:max_content_length]
    message = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": PROMPT_TEMPLATE.format(raw_content=truncated)}],
    )
    text_block = next(block for block in message.content if block.type == "text")
    text = text_block.text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def summarize(post: dict) -> dict:
    """post['raw_content']를 Claude API로 요약하고, 결과를 DB에 저장한다."""
    cfg = _load_summarizer_config()
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"].strip())

    result = None
    last_error = None
    for _attempt in range(2):
        try:
            result = _call_claude(client, cfg["model"], post["raw_content"], cfg["max_content_length"])
            break
        except (json.JSONDecodeError, KeyError, IndexError, StopIteration) as exc:
            last_error = exc
            continue

    if result is None:
        update_post_status(post["post_id"], "summarize_failed")
        raise ValueError(f"summarize failed for {post['post_id']}: {last_error}")

    keywords_str = ",".join(result["keywords"])
    update_post_status(post["post_id"], "summarized", summary=result["summary"], keywords=keywords_str)

    return {
        "post_id": post["post_id"],
        "summary": result["summary"],
        "keywords": result["keywords"],
    }
