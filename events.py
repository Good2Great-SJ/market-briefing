# -*- coding: utf-8 -*-
"""
"체크해야 할 주요 증시 이벤트" 캘린더.

기존엔 총평(narr)의 calendar 필드로 AI가 원문에서 언급한 일정을 뽑아썼는데,
그날 다루는 원문에 뭐가 언급됐는지에 따라 내용이 들쭉날쭉했다. 대신 이 모듈은
아래 네 가지를 코드로 직접 관리해 매번 일관된 이벤트 목록을 만든다:

  1. FOMC 회의 일정   — 연준이 연초에 그 해 전체 일정을 공식 발표(연 8회) → 하드코딩
  2. 금통위 회의 일정  — 한국은행도 마찬가지로 연간 일정을 미리 공지 → 하드코딩
  3. KRX 옵션/선물 만기일(쿼드러플 위칭) — "3·6·9·12월 둘째 목요일"이라는 고정
     규칙이라 계산으로 생성(유지보수 불필요)
  4. 주요 기업 실적 발표일 — yfinance(이미 쓰는 라이브러리)의 get_earnings_dates()로
     조회. 개별 기업 실적일은 그때그때 공지되는 특성상 하드코딩이 불가능해 이것만
     동적으로 가져온다.

**매년 갱신 필요**: 아래 _FOMC_2026 / _BOK_2026 리스트는 매년 초, 연준/한국은행이
그 해 일정을 공식 발표하면 그 값으로 교체해야 한다(각 기관 홈페이지 참고).
"""
import datetime

KST = datetime.timezone(datetime.timedelta(hours=9))

# 연준 공식 발표(federalreserve.gov) 기준 2026년 FOMC 전체 일정.
_FOMC_2026 = [
    (datetime.date(2026, 1, 28), "FOMC 회의 결과 발표(1/27~28)"),
    (datetime.date(2026, 3, 18), "FOMC 회의 결과 발표(3/17~18) · 경제전망 포함"),
    (datetime.date(2026, 4, 29), "FOMC 회의 결과 발표(4/28~29)"),
    (datetime.date(2026, 6, 17), "FOMC 회의 결과 발표(6/16~17) · 경제전망 포함"),
    (datetime.date(2026, 7, 29), "FOMC 회의 결과 발표(7/28~29)"),
    (datetime.date(2026, 9, 16), "FOMC 회의 결과 발표(9/15~16) · 경제전망 포함"),
    (datetime.date(2026, 10, 28), "FOMC 회의 결과 발표(10/27~28)"),
    (datetime.date(2026, 12, 9), "FOMC 회의 결과 발표(12/8~9) · 경제전망 포함"),
]

# 한국은행 공식 발표(bok.or.kr) 기준 2026년 통화정책방향 결정회의(금통위) 일정.
_BOK_2026 = [
    (datetime.date(2026, 1, 15), "금통위 기준금리 결정"),
    (datetime.date(2026, 2, 26), "금통위 기준금리 결정"),
    (datetime.date(2026, 4, 10), "금통위 기준금리 결정"),
    (datetime.date(2026, 5, 28), "금통위 기준금리 결정"),
    (datetime.date(2026, 7, 16), "금통위 기준금리 결정"),
    (datetime.date(2026, 8, 27), "금통위 기준금리 결정"),
    (datetime.date(2026, 10, 22), "금통위 기준금리 결정"),
    (datetime.date(2026, 11, 26), "금통위 기준금리 결정"),
]

# 실적 발표를 추적할 대표 종목(과도한 API 호출 방지를 위해 대형주 위주로 제한).
_EARNINGS_TICKERS = [
    ("AAPL", "애플"), ("MSFT", "마이크로소프트"), ("GOOGL", "구글"),
    ("AMZN", "아마존"), ("META", "메타"), ("NVDA", "엔비디아"), ("TSLA", "테슬라"),
    ("MU", "마이크론"), ("TSM", "TSMC"),
    ("005930.KS", "삼성전자"), ("000660.KS", "SK하이닉스"),
]


def _quad_witching_dates(year):
    """3·6·9·12월 둘째 목요일(KRX 옵션·선물 동시만기일)을 계산한다."""
    out = []
    for month in (3, 6, 9, 12):
        d = datetime.date(year, month, 1)
        thursdays = []
        while d.month == month:
            if d.weekday() == 3:  # 목요일
                thursdays.append(d)
            d += datetime.timedelta(days=1)
        out.append((thursdays[1], "국내 옵션·선물 동시만기(쿼드러플 위칭)"))
    return out


def _earnings_events(today, days_ahead):
    """yfinance로 대표 종목의 향후 실적 발표 예정일을 조회한다.
    개별 요청 실패(일시적 네트워크 오류 등)는 조용히 건너뛴다."""
    import yfinance as yf
    out = []
    end = today + datetime.timedelta(days=days_ahead)
    for ticker, name in _EARNINGS_TICKERS:
        try:
            df = yf.Ticker(ticker).get_earnings_dates(limit=4)
            if df is None or df.empty:
                continue
            for ts in df.index:
                d = ts.date()
                if today <= d <= end:
                    out.append((d, f"{name} 실적 발표 예정"))
        except Exception:
            continue
    return out


def get_upcoming_events(today=None, days_ahead=45):
    """오늘 기준 앞으로 days_ahead일 이내의 주요 증시 이벤트를 날짜순으로 반환.
    반환 형식은 기존 narr calendar 필드와 동일하게 맞춘다:
    [{"date": "YYYY-MM-DD", "event": "..."}]
    """
    today = today or datetime.datetime.now(KST).date()
    end = today + datetime.timedelta(days=days_ahead)

    events = []
    for d, label in _FOMC_2026 + _BOK_2026:
        if today <= d <= end:
            events.append((d, label))
    for d, label in _quad_witching_dates(today.year):
        if today <= d <= end:
            events.append((d, label))
    if today.month >= 11:  # 연말이면 다음 해 만기일도 미리 확인
        for d, label in _quad_witching_dates(today.year + 1):
            if today <= d <= end:
                events.append((d, label))
    try:
        events += _earnings_events(today, days_ahead)
    except Exception as e:
        print("  ! 실적 발표일 조회 실패:", repr(e)[:150])

    events.sort(key=lambda x: x[0])
    return [{"date": d.isoformat(), "event": label} for d, label in events]
