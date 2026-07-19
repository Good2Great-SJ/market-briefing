# -*- coding: utf-8 -*-
"""
AI-Tech 뉴스 로더.
  chatgpt-ai-tech/daily/YYYY-MM-DD-morning.md   (us 세션 — KST 아침 발행 리포트용)
  chatgpt-ai-tech/daily/YYYY-MM-DD-afternoon.md (kr 세션 — KST 저녁 발행 리포트용)
  이 마크다운 파일들은 market-briefing 저장소 자체에 별도 파이프라인이 커밋해
  넣는 것을 전제로 한다(이 모듈은 있으면 읽어서 렌더링하고, 없으면 조용히
  생략한다 — 버터대디/증시각도기 원천 콘텐츠가 없을 때와 동일한 패턴).

  버터대디/증시각도기와 달리 이 파이프라인은 거래일과 무관하게 매일(주말
  포함) KST 캘린더 기준으로 발행되므로, 시장 데이터 기준일(ref_date)이 아닌
  "리포트가 실제로 생성되는 오늘 날짜"로 매칭한다(주말·휴장일에는 시장
  기준일과 어긋날 수 있어 market-day 오프셋을 쓰면 안 됨).
"""
import os, datetime

_ROOT = os.path.dirname(__file__)
_SUFFIX = {"us": "morning", "kr": "afternoon"}


def get_ai_tech_markdown(session, publish_date):
    """
    session: 'us' | 'kr'.  publish_date: 리포트가 생성되는 오늘 날짜(KST, datetime.date).
    반환: (raw_markdown, file_date) 또는 (None, None)(파일이 아직 없으면).
    """
    suffix = _SUFFIX.get(session)
    if not suffix:
        return None, None
    path = os.path.join(_ROOT, "chatgpt-ai-tech", "daily", f"{publish_date.isoformat()}-{suffix}.md")
    if not os.path.exists(path):
        return None, None
    with open(path, encoding="utf-8") as f:
        return f.read(), publish_date
