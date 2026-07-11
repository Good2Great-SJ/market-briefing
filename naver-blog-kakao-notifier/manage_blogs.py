import os
import re
import sys

import yaml

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
BLOG_LINE_PATTERN = re.compile(r'^( *- blog_id: ")([^"]+)(")[ \t]*$', re.MULTILINE)


def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def add_blog(blog_id: str) -> bool:
    """config.yaml의 blogs 목록에 blog_id를 추가한다. 이미 있으면 아무 것도 하지 않는다."""
    cfg = _load_config()
    existing_ids = [b["blog_id"] for b in cfg.get("blogs") or []]
    if blog_id in existing_ids:
        print(f"이미 등록된 블로그입니다: {blog_id}")
        return False

    with open(CONFIG_PATH, encoding="utf-8") as f:
        text = f.read()

    matches = list(BLOG_LINE_PATTERN.finditer(text))
    if matches:
        insert_pos = matches[-1].end()
        text = text[:insert_pos] + f'\n  - blog_id: "{blog_id}"' + text[insert_pos:]
    else:
        text = text.replace("blogs:", f'blogs:\n  - blog_id: "{blog_id}"', 1)

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"블로그 추가 완료: {blog_id}")
    return True


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("사용법: python manage_blogs.py <blog_id>")
        sys.exit(1)
    add_blog(sys.argv[1])
