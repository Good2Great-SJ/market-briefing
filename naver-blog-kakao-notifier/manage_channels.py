import os
import re
import sys

import requests
import yaml

from manage_blogs import _simplify_name

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) naver-blog-kakao-notifier"}
CANONICAL_PATTERN = re.compile(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]+)"')
TITLE_PATTERN = re.compile(r"<title>([^<]+)</title>")


def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _normalize_handle(handle_or_url: str) -> str:
    handle = handle_or_url.strip()
    if "youtube.com/@" in handle:
        handle = handle.split("youtube.com/@")[-1]
    return handle.lstrip("@").split("/")[0].split("?")[0]


def _resolve_channel(handle: str) -> tuple[str, str]:
    """@handle로 채널 페이지를 조회해 (channel_id, 채널 제목)을 반환한다."""
    resp = requests.get(f"https://www.youtube.com/@{handle}", headers=HEADERS, timeout=10)
    resp.raise_for_status()

    match = CANONICAL_PATTERN.search(resp.text)
    if not match:
        raise ValueError(f"채널 ID를 찾을 수 없습니다: @{handle}")
    channel_id = match.group(1)

    title_match = TITLE_PATTERN.search(resp.text)
    title = title_match.group(1).replace(" - YouTube", "") if title_match else handle
    return channel_id, title


def add_channel(handle_or_url: str) -> bool:
    """config.yaml의 youtube_channels 목록에 채널을 추가한다."""
    handle = _normalize_handle(handle_or_url)
    cfg = _load_config()
    channels = cfg.get("youtube_channels") or []

    channel_id, channel_title = _resolve_channel(handle)

    if any(c["channel_id"] == channel_id for c in channels):
        print(f"이미 등록된 채널입니다: @{handle}")
        return False

    name = _simplify_name(channel_title)
    print(f"채널 제목: {channel_title} -> 표시 이름: {name}")

    with open(CONFIG_PATH, encoding="utf-8") as f:
        lines = f.readlines()

    if not any(line.strip() == "youtube_channels:" for line in lines):
        if lines and lines[-1].strip() != "":
            lines.append("\n")
        lines.append("youtube_channels:\n")

    yt_start = next(i for i, line in enumerate(lines) if line.strip() == "youtube_channels:")
    insert_at = yt_start + 1
    while insert_at < len(lines) and (
        lines[insert_at].startswith("  - channel_id:")
        or lines[insert_at].startswith("    name:")
        or lines[insert_at].startswith("    handle:")
    ):
        insert_at += 1

    new_lines = [
        f'  - channel_id: "{channel_id}"\n',
        f'    name: "{name}"\n',
        f'    handle: "{handle}"\n',
    ]
    lines[insert_at:insert_at] = new_lines

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"채널 추가 완료: @{handle} ({name})")
    return True


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("사용법: python manage_channels.py <handle 또는 URL>")
        sys.exit(1)
    add_channel(sys.argv[1])
