import json
import os

import yaml
from anthropic import Anthropic
from dotenv import load_dotenv

from db.db import update_post_status

load_dotenv()

PROMPT_TEMPLATE = """\
다음 글을 한국어로 요약하고, 핵심 키워드 3개를 뽑아줘.
요약은 카카오톡 메시지로 발송되며 시스템이 초과분을 자동으로 안전하게 정리하니,
글자 수를 미리 줄이려 하지 말고 원문의 정보량에 맞춰 충실하게 작성해줘:
- 원문 내용이 많으면 포인트 수를 늘리고(최대 7~8개까지 가능), 내용이 적으면 짧게 끝내도 됨
- 각 포인트는 "• "로 시작하고, 배경/수치/근거 등 구체적인 내용을 담아 1~3문장으로 작성
- 포인트 사이는 줄바꿈(\\n)으로 구분
- 다만 시스템이 뒤쪽부터 잘라낼 수 있으므로, 가장 중요한 포인트를 앞쪽에 배치해줘
- summary 전체는 대략 700자 내외를 기준으로 삼되, 원문이 풍부하면 그보다 길어져도 괜찮음

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
        max_tokens=2048,
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
