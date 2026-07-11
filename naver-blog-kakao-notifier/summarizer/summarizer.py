import json
import os

import yaml
from anthropic import Anthropic
from dotenv import load_dotenv

from db.db import update_post_status

load_dotenv()

PROMPT_TEMPLATE = """\
다음 블로그 글을 한국어로 3줄 이내로 요약하고, 핵심 키워드 3개를 뽑아줘.
반드시 아래 JSON 형식으로만 응답:
{{
  "summary": "...",
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
