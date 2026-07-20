# -*- coding: utf-8 -*-
"""
버터대디(블로그) / 증시각도기(유튜브) 원천 콘텐츠 로더.

naver-blog-kakao-notifier가 이미 수집·요약해 쌓아둔 state.db를 그대로 읽어
market-briefing 총평의 1차 근거로 사용한다.

채택 조건 (둘 다 만족해야 함):
  1) 날짜 일치 — 제목에 날짜가 명시돼 있으면(예: "7.16(목)", "[7월 18일 토요일 미국시황]")
     그 날짜를, 없으면 발행시각(KST 캘린더 날짜)을 리포트의 "기대 날짜"와 정확히 비교.
     세션별 기대 날짜: us = ref_date(미국장 마감 거래일)+1일, kr = ref_date(한국장 마감 거래일) 그대로.
  2) 세션(주제) 일치 — 증시각도기는 제목에 "미국시황"/"한국시황"이 명시돼 있어 그걸
     최우선으로 사용해 구분한다. 그런 태그가 없는 글(버터대디 등)은 발행시각의 KST
     시간대(아침=미국장 리캡, 저녁=한국장 리캡)로 판정한다.
  둘 중 하나라도 어긋나면 "아직 미발행"으로 간주해 사용하지 않는다.
"""
import os, re, sqlite3, datetime

NOTIFIER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "naver-blog-kakao-notifier"))
DB_PATH = os.path.join(NOTIFIER_DIR, "state.db")

BUTTERDADDY_BLOG_ID = "butterdaddy"
JEUNGSI_CHANNEL_ID = "UCdOjVxkj5JA0iDu3_xcsTyQ"  # 증시각도기 (config.yaml 기준)

_SOURCE_NAMES_CACHE = None


def _all_source_names():
    """
    naver-blog-kakao-notifier/config.yaml에 등록된 모든 블로그·유튜브 채널의
    {id: 표시이름} 매핑. 총평(버터대디/증시각도기) 산출용이 아니라, '주요 블로그
    및 영상' 목록에 수집 중인 소스 전체를 보여주기 위한 용도.
    """
    global _SOURCE_NAMES_CACHE
    if _SOURCE_NAMES_CACHE is not None:
        return _SOURCE_NAMES_CACHE
    names = {}
    try:
        import yaml
        with open(os.path.join(NOTIFIER_DIR, "config.yaml"), encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        for b in cfg.get("blogs", []) or []:
            if b.get("blog_id"):
                names[b["blog_id"]] = b.get("name") or b["blog_id"]
        for c in cfg.get("youtube_channels", []) or []:
            if c.get("channel_id"):
                names[c["channel_id"]] = c.get("name") or c["channel_id"]
    except Exception:
        pass
    _SOURCE_NAMES_CACHE = names
    return names

KST = datetime.timezone(datetime.timedelta(hours=9))
LOOKBACK_ROWS = 8  # 최근 N개 글/영상 중에서 기대 날짜+세션과 일치하는 것을 찾는다

# 버터대디는 하루 두 번(미국장 리캡=KST 아침, 한국장 리캡=KST 저녁) 올린다.
# 발행시각(KST)으로 어느 세션 글인지 구분. 증시각도기는 늘 아침대 업로드 → 자연히 us만 매칭.
_HOUR_RANGE = {"us": (3, 13), "kr": (14, 23)}

_DATE_PATTERNS = [
    re.compile(r"(\d{1,2})[.\-/월]\s*(\d{1,2})\s*일?"),  # 7.16 / 7-16 / 7/16 / 7월 16일
]


def _extract_title_date(title, year_hint):
    """제목에서 M.D 형태 날짜를 뽑아 그 해의 date로 변환. 못 찾으면 None."""
    if not title:
        return None
    for pat in _DATE_PATTERNS:
        m = pat.search(title)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            if 1 <= month <= 12 and 1 <= day <= 31:
                try:
                    return datetime.date(year_hint, month, day)
                except ValueError:
                    continue
    return None


def expected_date(session, ref_date):
    """세션별로 원천 콘텐츠가 다뤄야 할 '기대 날짜'(KST 캘린더 기준)."""
    if session == "us":
        return ref_date + datetime.timedelta(days=1)
    return ref_date


def _row_effective_date(row):
    """제목에 명시된 날짜 우선, 없으면 published_at의 KST 캘린더 날짜."""
    pub = row["_published_dt"]
    title_date = _extract_title_date(row["title"], pub.year)
    if title_date:
        return title_date
    return pub.astimezone(KST).date()


_SIHWANG_PATTERN = re.compile(r"(\S+)시황")


def _title_session_hint(title):
    """
    제목에 'OO시황' 태그가 있으면(증시각도기가 주로 사용) 그걸 최우선 판정 기준으로 쓴다.
    '미국시황'→us, '한국시황'→kr, 그 외('중국시황' 등)는 두 세션 어디에도 해당하지
    않는 별개 주제이므로 "other"로 명시적으로 제외한다(시간대 폴백으로 잘못 채택되는 것 방지).
    """
    if not title:
        return None
    m = _SIHWANG_PATTERN.search(title)
    if not m:
        return None
    tag = m.group(1)
    if "미국" in tag:
        return "us"
    if "한국" in tag:
        return "kr"
    return "other"


def _matches_session(row, session):
    """
    어느 세션(미국장/한국장) 콘텐츠인지 판정.
    1순위: 제목의 'OO시황' 태그. 2순위: 태그가 없으면 발행시각(KST 시간대)으로 판정(버터대디 등).
    """
    hint = _title_session_hint(row["title"])
    if hint == "other":
        return False
    if hint is not None:
        return hint == session
    lo, hi = _HOUR_RANGE[session]
    hour = row["_published_dt"].astimezone(KST).hour
    return lo <= hour <= hi


def _fetch_candidates(blog_id, limit=LOOKBACK_ROWS):
    if not os.path.exists(DB_PATH):
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT post_id, blog_id, title, url, published_at, summary, raw_content, status "
        "FROM posts WHERE blog_id = ? ORDER BY published_at DESC LIMIT ?",
        (blog_id, limit),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        item = dict(r)
        try:
            pub = datetime.datetime.fromisoformat(item["published_at"])
        except Exception:
            continue
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=datetime.timezone.utc)
        item["_published_dt"] = pub
        out.append(item)
    return out


def _find_matching(blog_id, want_date, session):
    """
    날짜가 맞는 후보 중에서, 'OO시황' 명시 태그로 세션이 정확히 확인된 것을 최우선으로
    선택한다(발행시각이 더 늦은 미태그 글이 먼저 스캔돼 태그된 글을 가리는 것을 방지).
    태그된 후보가 없을 때만 발행시각 기반 폴백 매칭으로 넘어간다.
    """
    candidates = [c for c in _fetch_candidates(blog_id) if _row_effective_date(c) == want_date]
    for item in candidates:
        if _title_session_hint(item["title"]) == session:
            return item
    for item in candidates:
        if _matches_session(item, session):
            return item
    return None


def ensure_summary(item):
    """summary가 비어있으면(아직 요약 전) naver-blog-kakao-notifier의 summarizer로 즉석 요약."""
    if not item or item.get("summary"):
        return item
    if not item.get("raw_content"):
        return item
    try:
        import sys
        from dotenv import load_dotenv
        load_dotenv(os.path.join(NOTIFIER_DIR, ".env"))
        sys.path.insert(0, NOTIFIER_DIR)
        from summarizer.summarizer import summarize
        result = summarize({"post_id": item["post_id"], "raw_content": item["raw_content"]})
        item["summary"] = result.get("summary", "")
    except Exception as e:
        print("  ! 즉석 요약 실패:", repr(e)[:150])
    return item


def get_sources_for_label_date(want_date, session):
    """want_date(기대 날짜, KST 캘린더)와 session(미국/한국 리캡 시간대)을 모두 만족하는 것만 채택."""
    bd = ensure_summary(_find_matching(BUTTERDADDY_BLOG_ID, want_date, session))
    jg = ensure_summary(_find_matching(JEUNGSI_CHANNEL_ID, want_date, session))
    return {"butterdaddy": bd, "증시각도기": jg}


def get_session_sources(session, ref_date):
    """
    session: 'us' | 'kr'
    ref_date: 리포트의 데이터 기준일(datetime.date) — 세션에 맞는 시장의 마지막 거래일.
    반환: {"butterdaddy": item|None, "증시각도기": item|None}
    """
    return get_sources_for_label_date(expected_date(session, ref_date), session)


def get_sources_for_range(start_date, end_date, session):
    """
    [start_date, end_date] 구간에서 버터대디/증시각도기 각각 가장 관련성 높은
    (세션 태그 일치 우선, 그다음 최신) 항목 하나씩을 찾는다.
    거래일 공백(주말 등) 직후의 리포트에서 정확히 하루만 보면 놓치는 주말
    콘텐츠까지 총평에 반영하기 위한 용도 — get_sources_for_label_date의
    구간 버전.
    """
    def _best(blog_id):
        candidates = [c for c in _fetch_candidates(blog_id)
                      if start_date <= _row_effective_date(c) <= end_date]
        if not candidates:
            return None
        candidates.sort(key=lambda c: c["published_at"], reverse=True)
        # "장전"(프리마켓) 영상은 리포트 발행 당일 아침 상황을 가장 직접적으로
        # 다루므로, "OO시황" 태그보다도 우선한다 — 특히 월요일 장전 리포트에서
        # (구간 마지막 날 = 오늘 올라온 것만 해당, 주말 중 올라온 옛날 "장전" 글까지
        # 끌어오지 않도록 end_date와 일치하는 것만 본다).
        for c in candidates:
            if re.search(r"장\s*전", c["title"]) and _row_effective_date(c) == end_date:
                return c
        for c in candidates:
            if _title_session_hint(c["title"]) == session:
                return c
        for c in candidates:
            if _matches_session(c, session):
                return c
        return candidates[0]  # 태그·시간대 매칭이 안 돼도 구간 안 최신 글은 채택(주말 예외라 관대하게)

    bd = ensure_summary(_best(BUTTERDADDY_BLOG_ID))
    jg = ensure_summary(_best(JEUNGSI_CHANNEL_ID))
    return {"butterdaddy": bd, "증시각도기": jg}


def has_any(sources):
    return bool(sources) and any(sources.values())


def get_post_by_id(post_id):
    """단일 post_id의 현재 DB 상태를 조회한다.

    라이브 방송 등은 처음 수집될 때 자막이 아직 없어 status=transcript_pending으로
    설명란만 채워둔 채 저장되고, naver-blog-kakao-notifier의 retry_pending_transcripts가
    나중에 실제 자막을 채워 status=collected로 승격시킨다. trigger.py가 이 상태 변화를
    감지해 총평에 반영이 덜 된 리포트를 재발행할 때 쓴다.
    """
    if not os.path.exists(DB_PATH):
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT post_id, blog_id, title, url, published_at, summary, raw_content, status "
        "FROM posts WHERE post_id = ?", (post_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


MAX_RAW_CHARS = 8000


def _all_tracked_ids():
    """config.yaml에 등록된 소스 + DB에 실제 존재하는 blog_id(설정 누락 대비 안전망)."""
    names = dict(_all_source_names())
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            for (bid,) in conn.execute("SELECT DISTINCT blog_id FROM posts"):
                names.setdefault(bid, bid)
            conn.close()
        except Exception:
            pass
    return names


def list_recent_sources(session, ref_date, monday_includes_weekend=True, want_date_override=None):
    """
    리포트 데이터 기준일까지 수집되어 있는 원문 글/영상 목록(최신순).
    총평 생성에 실제로 쓰인 것 외에도, 해당 세션의 '기대 날짜'까지 올라온
    글/영상을 전부 보여주기 위한 용도(리포트의 '수집 현황' 섹션).
    월요일 리포트는 주말(토·일) 동안 올라온 글도 함께 포함한다.
    want_date_override: 지정하면 '기대 날짜'를 이 날짜로 대체한다(거래일 갭으로
    expected_date()가 실제 오늘과 어긋날 때 사용).
    """
    want = want_date_override or expected_date(session, ref_date)
    start = want
    if monday_includes_weekend and want.weekday() == 0:  # 월요일
        start = want - datetime.timedelta(days=2)

    out = []
    for blog_id, label in _all_tracked_ids().items():
        for item in _fetch_candidates(blog_id):
            d = _row_effective_date(item)
            if start <= d <= want:
                out.append(dict(
                    source=label, title=item["title"], url=item["url"],
                    published_at=item["published_at"], date=d.isoformat(),
                    summary=(item.get("summary") or "").strip(),
                ))
    out.sort(key=lambda x: x["published_at"], reverse=True)
    return out


def list_week_sources(start_date, end_date, limit_per_blog=40):
    """
    [start_date, end_date](effective date 기준, 양끝 포함) 구간의 원문 전체.
    추적 중인 모든 블로그·유튜브 채널 대상. list_recent_sources와 달리
    LOOKBACK_ROWS(8) 제한 없이 한 주치를 넉넉히 가져온다.
    """
    out = []
    for blog_id, label in _all_tracked_ids().items():
        for item in _fetch_candidates(blog_id, limit=limit_per_blog):
            d = _row_effective_date(item)
            if start_date <= d <= end_date:
                out.append(dict(
                    source=label, title=item["title"], url=item["url"],
                    published_at=item["published_at"], date=d.isoformat(),
                    summary=(item.get("summary") or "").strip(),
                    raw_content=(item.get("raw_content") or "").strip(),
                ))
    out.sort(key=lambda x: x["date"])
    return out


def to_prompt_block(sources):
    """
    narrative.py 프롬프트에 삽입할 원천 콘텐츠 텍스트 블록.
    naver-blog-kakao-notifier가 만든 summary는 자체 요약 과정에서 주어(어느 나라/
    시장 얘기인지) 오류가 발생한 사례가 확인되어, 신뢰도가 더 높은 원본
    (raw_content — 자막/본문 원문)을 우선 사용한다. summary는 raw_content가
    없을 때만 보조로 사용.
    """
    parts = []
    for label, item in (sources or {}).items():
        if not item:
            continue
        raw = (item.get("raw_content") or "").strip()
        if raw:
            text = raw[:MAX_RAW_CHARS]
            parts.append(f"[{label} — {item['title']}] ({item['published_at']}) [원본 자막/본문]\n{text}")
        elif item.get("summary"):
            parts.append(f"[{label} — {item['title']}] ({item['published_at']}) [요약본]\n{item['summary']}")
    return "\n\n".join(parts)
