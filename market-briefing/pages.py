# -*- coding: utf-8 -*-
"""
GitHub Pages 리포트 아카이브 발행.
  docs/reports/{session}_{theme}_{date}.html 로 리포트를 복사하고
  docs/manifest.json 에 (session, date) 기준으로 upsert한다.
  docs/index.html(뷰어)이 manifest.json을 읽어 드롭다운으로 과거/최신 리포트를 보여준다.
"""
import os, json, shutil, datetime

KST = datetime.timezone(datetime.timedelta(hours=9))

_ROOT = os.path.dirname(__file__)
_DOCS = os.path.join(_ROOT, "docs")
_REPORTS = os.path.join(_DOCS, "reports")
_MANIFEST = os.path.join(_DOCS, "manifest.json")

PAGES_BASE = "https://good2great-sj.github.io/market-briefing"


def _load_manifest():
    if not os.path.exists(_MANIFEST):
        return []
    try:
        with open(_MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def publish_report(session, theme, date_str, html_path, title=None, display_date=None):
    """
    생성된 리포트 HTML을 docs/reports/에 복사하고 manifest.json을 갱신한다.
    title: 아카이브 드롭다운에 표시할 리포트 제목. 거래일 공백(월요일 등) 리포트처럼
    session만으로는 실제 제목("한국증시 장전 리포트" 등)을 알 수 없는 경우에 넘긴다.
    생략하면 뷰어(index.html)가 session 기준 기본 라벨로 대체한다.
    date_str: 아카이브 키/파일명에 쓰이는 값 — 다른 리포트와 충돌 방지를 위해
    "2026-07-20-premarket"처럼 순수 날짜가 아닌 값이 들어올 수 있다.
    display_date: 드롭다운에 실제로 보여줄 깔끔한 날짜. 생략하면 date_str을 그대로
    쓴다(보통은 같지만, 위 충돌방지 키를 쓸 때는 꼭 넘겨야 사용자에게 이상한
    문자열이 안 보인다).
    반환값: (report_url, viewer_url) — 이메일 등에 바로 쓸 수 있는 절대 URL.
    """
    os.makedirs(_REPORTS, exist_ok=True)
    fname = f"{session}_{theme}_{date_str.replace('-', '')}.html"
    dest = os.path.join(_REPORTS, fname)
    shutil.copyfile(html_path, dest)

    manifest = _load_manifest()
    manifest = [r for r in manifest if not (r.get("session") == session and r.get("date") == date_str)]
    entry = dict(
        session=session, date=date_str, theme=theme,
        path=f"reports/{fname}",
        # naive datetime.now()는 실행 환경(로컬 vs GitHub Actions 러너=UTC)에 따라
        # 시간대가 달라 같은 날짜 안에서 정렬 순서가 실제 발행 순서와 어긋날 수
        # 있었다(2026-07-20 실제 발생) — 항상 KST로 고정한다.
        generated_at=datetime.datetime.now(KST).isoformat(timespec="seconds"),
    )
    if title:
        entry["title"] = title
    if display_date and display_date != date_str:
        entry["display_date"] = display_date
    manifest.append(entry)
    manifest.sort(key=lambda r: (r["date"], r["session"]), reverse=True)

    with open(_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    report_url = f"{PAGES_BASE}/reports/{fname}"
    viewer_url = f"{PAGES_BASE}/?session={session}&date={date_str}"
    return report_url, viewer_url
