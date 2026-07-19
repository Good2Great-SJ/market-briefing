# -*- coding: utf-8 -*-
"""
상단 총평 섹션 생성 (Claude API).
  1순위: 버터대디(블로그) / 증시각도기(유튜브)가 그날 발행한 실제 코멘터리(sources.py)
  2순위: 원천 콘텐츠가 없을 때만 웹서치로 보강
  실패 시 None 반환(리포트는 규칙 기반 총평으로 대체).
"""
import os, json, re
from dotenv import load_dotenv

load_dotenv()
load_dotenv("../stock-consensus-notifier/.env")

MODEL = "claude-sonnet-5"
_LABEL = {"us": "미국 증시 마감", "kr": "한국 증시 마감"}

_PROMPT_WITH_SOURCES = """당신은 한국 증권사의 데일리 마켓 브리핑을 작성하는 애널리스트입니다.
오늘은 {ref}이며, 이번 브리핑은 **{session_label}** 기준입니다.

아래 [원천 콘텐츠]는 버터대디(네이버 프리미엄 블로그)와 증시각도기(유튜브 채널)가
오늘 발행한 실제 시황 코멘터리입니다(유튜브는 자동 생성 자막 원문일 수 있어 오탈자·
오인식 단어가 섞여 있을 수 있습니다).

**중요 — 두 소스를 하나로 합치거나 압축하지 말고, 각각 별도로 정리하세요.**
버터대디 글이 있으면 "butterdaddy_analysis"에, 증시각도기 영상이 있으면
"jeungsi_analysis"에 그 소스의 논리와 시각을 담되, **각 필드는 1200자 이내로
정리하세요.** 원문이 다루는 핵심 논지·근거·수치·저자의 결론 위주로 정보 밀도
있게 압축하고, 지엽적인 반복이나 부연 설명은 생략하세요(짧은 요약이 아니라
1200자 한도 안에서 핵심을 빠짐없이 담는 것이 목표). 해당 소스가 없으면 그 필드는
null로 두세요. 하단 [데이터 요약]은 두 분석의 수치 근거를 보강하는 용도로만 참고하세요.

**형식 — 가독성을 위해 반드시 지킬 것**:
- 논지가 바뀌는 지점마다 문단을 나누고, 문단과 문단 사이는 \\n\\n(빈 줄 하나)으로
  구분하세요. 한 문단에 서로 다른 주제를 욱여넣지 말 것(문단당 3~5문장 권장).
- **마지막 문단은 반드시 "결론" 성격의 한 문단으로 마무리하세요.** 그날 분석 전체를
  관통하는 한줄 요약·시사점(예: 앞으로 주목할 점, 시장에 주는 함의)을 담아, 읽는
  사람이 마지막 문단만 봐도 핵심을 파악할 수 있게 쓰세요.

**정확성 주의사항 (반드시 지킬 것)**:
- 어떤 사실이 "어느 나라/시장"에 해당하는지 원문 문맥을 꼼꼼히 확인하고 절대 뒤바꾸지 마세요.
  (예: 한국 시장이 휴장이어서 영향을 피했다는 내용을 미국 시장 얘기로 착각하는 식의 주어
  오귀속 금지. 화자가 "저희"/"우리"라고 말하면 보통 한국(국내) 시장을 가리킵니다.)
- 문장 내부가 논리적으로 모순되면(예: "충격을 피했다"면서 동시에 "급락했다"고 서술) 그
  문장을 그대로 베끼지 말고, 원문을 다시 읽어 실제로 무슨 일이 있었는지 정확히 재구성하세요.
- 원문에 명시되지 않은 수치나 사실을 지어내지 마세요.
- 유튜브 자동 생성 자막은 오탈자·띄어쓰기 오류·문장이 뚝뚝 끊기는 구어체 특성상 그대로
  옮기면 어색하거나 비문에 가까운 문장이 섞이기 쉽습니다. 원문의 사실관계·수치·논지는
  그대로 유지하되, 문장 자체는 매끄러운 한국어 서술문으로 다듬어서 쓰세요(자막을 그대로
  베껴쓰지 말 것). 의미가 불명확한 구간은 앞뒤 문맥으로 자연스럽게 재구성하세요.

[원천 콘텐츠]
{sources}

[데이터 요약]
{digest}

다음 JSON 형식으로만 답하세요(마크다운·설명 없이 JSON만. \\n\\n으로 단락 구분):
{{
  "butterdaddy_analysis": "버터대디 글 분석(1200자 이내) 또는 null",
  "jeungsi_analysis": "증시각도기 영상 분석(1200자 이내) 또는 null",
  "checkpoints": ["두 소스가 강조한 체크포인트, 개수 제한 없이 원문에 있는 만큼"],
  "news": [{{"title":"소스가 언급한 시장 영향 뉴스/이벤트","impact":"영향 한 줄"}}],
  "calendar": [{{"date":"아래 date 형식 규칙을 따른 표기","event":"소스가 언급한, 앞으로 체크해야 할 이벤트"}}],
  "sources_used": ["실제로 반영한 원천 이름들, 예: 버터대디, 증시각도기"]
}}

**calendar의 date 형식 규칙 (모든 항목이 같은 규칙을 따라야 함 — 형식이 제각각이면 안 됨)**:
- 오늘({ref}) 기준으로 "내년"/"내후년"/"올해" 같은 상대적 표현은 반드시 절대 연도(YYYY)로 환산해서 표기할 것.
- 시점의 구체성에 맞춰 아래 중 하나의 형식만 사용:
  · 구체적 날짜가 있으면: "YYYY-MM-DD"
  · 월 단위면: "YYYY년 MM월"
  · 분기 단위면: "YYYY년 N분기"
  · 반기 단위면: "YYYY년 상반기"/"YYYY년 하반기"
  · 연도만 언급되면: "YYYY년"
  · 여러 해에 걸친 범위면: "YYYY~YYYY년"
  · 연말/연초처럼 한 해 안의 시점이면: "YYYY년 연말"/"YYYY년 연초"
- calendar 배열은 가까운 시점 → 먼 시점 순으로 정렬할 것.

제약:
- 원천 콘텐츠에 없는 내용을 지어내지 말 것. calendar/news는 원천에 언급이 없으면 빈 배열로 둘 것.
- 특정 종목의 매수/매도 권유나 투자 조언은 하지 말 것.
- 존댓말. 분석 본문은 길어도 되지만, 불필요한 반복 없이 정보 밀도 있게 작성할 것.
"""

_PROMPT_NO_SOURCES = """당신은 한국 증권사의 데일리 마켓 브리핑을 작성하는 애널리스트입니다.
오늘은 {ref}이며, 이번 브리핑은 **{session_label}** 기준입니다.
버터대디/증시각도기의 오늘자 코멘터리가 아직 발행되지 않아, 아래 데이터만으로 작성합니다.

[데이터 요약]
{digest}

web_search 도구로 최근 시장 관련 실제 뉴스와 앞으로 체크해야 할 주요 이벤트
(FOMC/금통위, CPI·PPI 등 경제지표, 빅테크·주요기업 실적, 옵션·선물 만기 등)을 확인해 반영하세요.

다음 JSON 형식으로만 답하세요(마크다운·설명 없이 JSON만):
{{
  "overview": "장 흐름 총평 3~4문장. 데이터 근거로 오늘 시장을 요약.",
  "checkpoints": ["지금 주목할 체크포인트 3~5개, 각 한 문장"],
  "news": [{{"title":"시장에 영향을 준 실제 뉴스 헤드라인","impact":"영향 한 줄"}}],
  "calendar": [{{"date":"MM/DD 또는 요일","event":"앞으로 체크해야 할 이벤트"}}],
  "sources_used": []
}}

제약: 사실 위주 서술, 투자 권유 금지. news 3~5개, calendar 3~6개.
"""


def _extract_json(text):
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _generate_once(session, digest, ref, sources, api_key, attempt=0):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    label = _LABEL.get(session, "증시")

    src_block = ""
    if sources:
        import sources as srcmod  # noqa
        src_block = srcmod.to_prompt_block(sources)

    if src_block:
        prompt = _PROMPT_WITH_SOURCES.format(
            ref=ref, session_label=label, sources=src_block, digest=digest)
        tools = None  # 원천 콘텐츠가 있으면 웹서치 불필요(쿼터 절약)
        # "분량 제한 없이" 지시 특성상 8000 토큰에서 잘리는 경우가 있었음(모델이
        # assistant 메시지 프리필/이어쓰기를 지원하지 않아 이어붙이기 불가) —
        # 잘리면 재시도 때마다 예산을 늘려 다시 처음부터 생성한다.
        max_tokens = 8000 + attempt * 6000
    else:
        prompt = _PROMPT_NO_SOURCES.format(ref=ref, session_label=label, digest=digest)
        tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}]
        max_tokens = 2500 + attempt * 3000

    messages = [{"role": "user", "content": prompt}]
    kwargs = dict(model=MODEL, max_tokens=max_tokens, messages=messages)
    if tools:
        kwargs["tools"] = tools

    resp = client.messages.create(**kwargs)
    text = "".join(b.text for b in resp.content if b.type == "text")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError(f"max_tokens={max_tokens}에서 응답이 잘림")
    return _extract_json(text)


def generate(session, digest, ref, sources=None, api_key=None, max_retries=2):
    """
    일시적 API 오류(과부하·네트워크 등) 및 max_tokens 잘림에 대비해 재시도한다.
    잘림이 원인이면 재시도마다 예산을 늘려 다시 생성한다(이 모델은 assistant
    메시지 프리필을 지원하지 않아 이어쓰기가 불가능함).
    모든 시도가 실패하면 None을 반환(리포트는 규칙 기반 총평으로 대체).
    """
    api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    import time
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            data = _generate_once(session, digest, ref, sources, api_key, attempt=attempt)
            if data:
                return data
            last_err = "빈 응답(JSON 파싱 실패)"
        except Exception as e:
            last_err = repr(e)[:150]
        if attempt < max_retries:
            print(f"  ! narrative 시도 {attempt+1} 실패({last_err}) — 재시도…")
            time.sleep(2 * (attempt + 1))
    print("  ! narrative 최종 실패:", last_err)
    return None
