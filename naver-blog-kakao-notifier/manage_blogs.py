import os
import sys

import feedparser
import yaml
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
RSS_URL_TEMPLATE = "https://rss.blog.naver.com/{blog_id}.xml"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) naver-blog-kakao-notifier"}

NAME_EXAMPLES = """\
'메르의 블로그' -> '메르'
'버터대디 (butterdaddy)' -> '버터대디'
'James Lee Advisors' -> 'James Lee'
'이그전: 매크로 투자 전략' -> '이그전'
'plainVanilla' -> '플레인바닐라'
'FINANCIAL FREEDOM' -> '경제적자유'
'피우스의 책도둑 & 매거진' -> '피우스'
"""


def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _fetch_rss_title(blog_id: str) -> str:
    feed = feedparser.parse(RSS_URL_TEMPLATE.format(blog_id=blog_id), request_headers=HEADERS)
    return feed.feed.get("title", blog_id)


def _simplify_name(rss_title: str) -> str:
    """RSS 채널 제목을 짧은 필명/블로그 이름으로 정리한다. API 키가 없으면 원본 제목을 그대로 쓴다."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return rss_title

    client = Anthropic(api_key=api_key)
    prompt = (
        "다음은 블로그 RSS 피드의 채널 제목이다. 사람들이 실제로 부르는 짧고 간결한 "
        "필명/블로그 이름으로 정리해줘. 부제, 괄호, 설명 문구는 제거하고 핵심 이름만 남긴다. "
        "이름만 출력하고 다른 말은 하지 마라.\n\n"
        f"예시:\n{NAME_EXAMPLES}\n"
        f"'{rss_title}' -> "
    )
    message = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    text_block = next((block for block in message.content if block.type == "text"), None)
    if text_block is None:
        return rss_title
    name = text_block.text.strip().strip("'\"")
    return name or rss_title


def add_blog(blog_id: str) -> bool:
    """config.yaml의 blogs 목록에 blog_id를 추가한다. RSS 제목을 가져와 표시 이름을 자동 생성한다."""
    cfg = _load_config()
    existing_ids = [b["blog_id"] for b in cfg.get("blogs") or []]
    if blog_id in existing_ids:
        print(f"이미 등록된 블로그입니다: {blog_id}")
        return False

    rss_title = _fetch_rss_title(blog_id)
    name = _simplify_name(rss_title)
    print(f"RSS 제목: {rss_title} -> 표시 이름: {name}")

    with open(CONFIG_PATH, encoding="utf-8") as f:
        lines = f.readlines()

    blogs_start = next(i for i, line in enumerate(lines) if line.strip() == "blogs:")
    insert_at = blogs_start + 1
    while insert_at < len(lines) and (
        lines[insert_at].startswith("  - blog_id:") or lines[insert_at].startswith("    name:")
    ):
        insert_at += 1

    new_lines = [
        f'  - blog_id: "{blog_id}"\n',
        f'    name: "{name}"\n',
    ]
    lines[insert_at:insert_at] = new_lines

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"블로그 추가 완료: {blog_id} ({name})")
    return True


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("사용법: python manage_blogs.py <blog_id>")
        sys.exit(1)
    add_blog(sys.argv[1])
