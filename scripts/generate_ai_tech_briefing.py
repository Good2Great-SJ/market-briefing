#!/usr/bin/env python3
"""Generate a Korean AI, semiconductor, and technology news briefing."""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from openai import OpenAI


SINGAPORE = ZoneInfo("Asia/Singapore")
OUTPUT_DIR = Path("chatgpt-ai-tech/daily")
EDITIONS = ("morning", "afternoon")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edition", required=True, choices=EDITIONS)
    return parser.parse_args()


def build_prompt(edition: str, date: str, morning_briefing: str | None) -> str:
    edition_ko = "오전" if edition == "morning" else "오후"
    deduplication = ""
    if edition == "afternoon":
        if morning_briefing:
            deduplication = f"""

오늘 오전 브리핑 전문은 아래와 같다.
--- 오전 브리핑 시작 ---
{morning_briefing}
--- 오전 브리핑 끝 ---

오전 브리핑과 같은 사건은 원칙적으로 제외하라. 새로운 실적, 발표, 규제,
가격 변동, 공식 확인 등 사업 또는 투자 판단을 바꿀 만한 중대한 업데이트가
있는 경우에만 다시 다루고, 무엇이 새로워졌는지 명시하라.
"""
        else:
            deduplication = """

오전 브리핑 파일을 찾지 못했다. 검색 결과에서 이미 널리 보도된 오래된
소식보다 오늘 오후에 새로 확인된 중대한 업데이트를 우선하라.
"""

    return f"""
현재 날짜는 Asia/Singapore 기준 {date}이며, {edition_ko}판 브리핑을 작성한다.
웹 검색을 사용해 AI, 반도체, 기술 산업의 가장 중요하고 최신인 뉴스를 조사하라.
공식 발표, 규제기관, 기업 IR, 신뢰도 높은 주요 언론 등 원출처에 가까운 자료를
우선하고, 사실과 추론을 구분하라.

결과는 한국어 Markdown만 출력한다. 5~8개의 중요 항목을 선별하고 다음 형식을
정확히 따른다.

# {date} AI·반도체·테크 {edition_ko} 브리핑

## 핵심 요약
- 전체 흐름을 2~4개 불릿으로 요약

## 1. 헤드라인
- **한줄 요약:** ...
- **사업·산업적 의미:** ...
- **투자 시사점:** 단정적인 매수·매도 권유 없이 짧게 ...
- **출처:** [출처명](정확한 원문 URL), [출처명](정확한 원문 URL)

각 항목에는 실제로 확인한 출처명과 직접 URL을 반드시 포함하라. 링크가 없는
주장은 쓰지 말고, 같은 사건을 여러 항목으로 나누지 마라. 투자 시사점은
기회뿐 아니라 리스크와 불확실성도 간결하게 제시하라.
{deduplication}
""".strip()


def main() -> None:
    args = parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required")

    now = datetime.now(SINGAPORE)
    date = now.date().isoformat()
    output_path = OUTPUT_DIR / f"{date}-{args.edition}.md"

    if output_path.exists():
        raise SystemExit(f"Refusing to overwrite existing briefing: {output_path}")

    morning_briefing = None
    if args.edition == "afternoon":
        morning_path = OUTPUT_DIR / f"{date}-morning.md"
        if morning_path.is_file():
            morning_briefing = morning_path.read_text(encoding="utf-8")

    model = os.environ.get("OPENAI_MODEL", "gpt-5.6-terra")
    response = OpenAI().responses.create(
        model=model,
        tools=[
            {
                "type": "web_search",
                "search_context_size": "high",
                "user_location": {
                    "type": "approximate",
                    "country": "SG",
                    "city": "Singapore",
                    "timezone": "Asia/Singapore",
                },
            }
        ],
        input=build_prompt(args.edition, date, morning_briefing),
    )

    briefing = response.output_text.strip()
    if not briefing:
        raise RuntimeError("OpenAI returned an empty briefing")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with output_path.open("x", encoding="utf-8", newline="\n") as output_file:
            output_file.write(briefing)
            output_file.write("\n")
    except FileExistsError as exc:
        raise SystemExit(
            f"Refusing to overwrite existing briefing: {output_path}"
        ) from exc

    print(output_path)


if __name__ == "__main__":
    main()
