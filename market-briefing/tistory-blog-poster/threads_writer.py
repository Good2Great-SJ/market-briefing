# -*- coding: utf-8 -*-
"""
Threads로 블로그 외부유입을 만들기 위한 캡션 작성.
  Higgsfield 영상 없이도 동작 — Tistory에 이미 올라간 대표이미지 URL과 함께
  텍스트 훅만으로 클릭을 유도하는 것이 목표.
"""
import os, re, json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from dotenv import load_dotenv

_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_HERE, ".env"))
load_dotenv(os.path.join(_HERE, "..", "stock-consensus-notifier", ".env"))

MODEL = "claude-sonnet-5"

_PROMPT = """당신은 경제/주식 블로그 'doleman'의 Threads 에디터입니다.
목표는 단순 요약이나 과장형 클릭베이트가 아니라, Threads 안에서 독립적으로 가치 있는
관점 하나를 주면서도 독자가 블로그 원문을 클릭해야 결론과 실전 해석을 얻도록 만드는 것입니다.

[블로그 글 제목]
{title}

[블로그 글 본문(HTML, 참고용 — 그대로 요약하지 말 것)]
{body_html}

성과형 작성 구조:
1) 첫 줄: 1초 안에 피드를 멈추게 할 구체적인 숫자·역설·의외의 대비 하나. 제목을 그대로 반복하지 말 것.
2) 중간: 독자가 이미 안다고 생각한 통념과 실제 데이터가 어디서 갈리는지 1~2문장.
3) 클릭 이유: 원문에서 확인할 분석 기준·체크포인트·실전 의미를 구체적으로 예고하되
   핵심 결론은 공개하지 말 것. 막연한 "자세한 내용은 블로그" 문구는 금지.
4) 대화 유도: 실제로 짧게 답할 수 있는 질문을 한 문장 넣을 것. 억지 질문이나
   "여러분 생각은?" 같은 빈 문구는 금지.
5) 마지막 줄: '{{LINK}}'를 반드시 단독으로 넣을 것.

세부 원칙:
- Threads 전용 원문처럼 자연스럽게 작성한다. 블로그 제목의 축약·요약문처럼 쓰지 않는다.
- 사실·숫자는 제공된 본문에서만 가져오고, 거짓 정보 공백이나 과장 표현을 만들지 않는다.
- 조회수 약속, 공포 조장, 의료적 단정은 금지한다. 강한 훅은 사실성과 구체성으로 만든다.
- 이미지가 전달하는 장면을 캡션 첫 줄에서 그대로 설명하지 말고 정보 격차를 만든다.
- 본문의 핵심 결론과 모든 근거를 다 알려주지 않는다. 독자가 링크를 눌러야 얻는 것이
  최소 하나(원인, 비교표, 체크포인트, 대응법 중 하나)는 반드시 남아야 한다.
- 첫 문장에 "충격", "대박", "이것만 알면", "모르면 손해" 같은 상투적 클릭베이트 금지.
- 문장은 짧게, 문단은 2~4개. 이모지는 0~1개.
- 해시태그 나열 금지. 가장 관련성 높은 주제어 하나가 꼭 필요할 때만 마지막 링크 앞에
  '#주제어' 하나를 허용한다.
- 링크를 제외하고 220~380자 권장, 절대 450자를 넘지 말 것.

다음 JSON 형식으로만 답하세요(마크다운 없이 JSON 객체 하나만):
{{
  "caption": "위 원칙을 따른 Threads 캡션 전체 텍스트(마지막 줄은 반드시 {{LINK}})",
  "click_reason": "독자가 링크를 눌러야만 알 수 있도록 남겨둔 정보 한 가지"
}}
"""


def _extract_json(text):
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(m.group(0)) if m else None


def write_caption(title, body_html, api_key=None, max_retries=2):
    """반환: '{LINK}' 자리표시자가 포함된 캡션 문자열."""
    import anthropic
    api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY가 설정되어 있지 않습니다.")
    client = anthropic.Anthropic(api_key=api_key)

    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = client.messages.create(
                model=MODEL, max_tokens=500,
                messages=[{"role": "user", "content": _PROMPT.format(title=title, body_html=body_html)}],
            )
            text = "".join(b.text for b in resp.content if b.type == "text")
            data = _extract_json(text)
            if data and data.get("caption") and "{LINK}" in data["caption"]:
                caption = data["caption"].strip()
                if not caption.endswith("{LINK}"):
                    last_err = "링크 자리표시자가 마지막 줄에 있지 않음"
                    continue
                visible = caption.replace("{LINK}", "").strip()
                if len(visible) > 450:
                    last_err = f"캡션이 너무 김({len(visible)}자)"
                    continue
                if not data.get("click_reason"):
                    last_err = "클릭 이유가 검증되지 않음"
                    continue
                return caption
            last_err = f"빈 응답 또는 형식 오류: {text[:200]}"
        except Exception as e:
            last_err = repr(e)[:200]
    raise RuntimeError(f"Threads 캡션 생성 실패: {last_err}")


def _tracked_url(url, campaign):
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({
        "utm_source": "threads",
        "utm_medium": "social",
        "utm_campaign": campaign,
    })
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def finalize_caption(template, url, campaign="tistory_daily", max_length=500):
    """Threads 500자 제한 안에서 UTM 링크와 핵심 문단을 보존한다."""
    visible = template.replace("{LINK}", "").strip()
    tracked = _tracked_url(url, campaign)
    final_url = tracked if len(tracked) <= 220 else url
    available = max_length - len(final_url) - 2
    paragraphs = [p.strip() for p in visible.split("\n\n") if p.strip()]
    while len("\n\n".join(paragraphs)) > available and len(paragraphs) > 2:
        paragraphs.pop(-2)
    compact = "\n\n".join(paragraphs)
    if len(compact) > available:
        compact = compact[:max(0, available - 1)].rstrip() + "…"
    caption = f"{compact}\n\n{final_url}"
    if len(caption) > max_length:
        raise RuntimeError(f"Threads 최종 캡션이 {max_length}자를 초과했습니다.")
    return caption
