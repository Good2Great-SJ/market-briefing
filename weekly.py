# -*- coding: utf-8 -*-
"""
주간 다이제스트.
  그 주(월~금)에 버터대디/증시각도기가 발행한 시황 코멘터리 원문 전체를 모아
  Claude로 핵심 키워드 후보·주요 이벤트·주간 총평을 뽑고, 키워드는 원문에서
  실제 등장 횟수를 프로그램으로 재검증한 뒤 이메일로 발송한다.

  토요일 아침(SGT) 1회 실행을 전제로 한다(금요일 한국·미국 마감 리포트가 모두
  나온 뒤). GitHub Actions에서 주 1회 cron으로 이 스크립트를 실행하면 된다.
"""
import os, sys, json, datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "stock-consensus-notifier", ".env"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SGT = datetime.timezone(datetime.timedelta(hours=8))
MARKER_DIR = os.path.join(os.path.dirname(__file__), "out", ".triggers")

_PROMPT = """당신은 한국 증권사의 주간 리서치 애널리스트입니다.
아래는 {start} ~ {end}(한 주간) 버터대디(네이버 프리미엄 블로그)와 증시각도기
(유튜브 채널)가 발행한 시황 코멘터리 원문 전체입니다.

[원문 목록]
{sources}

이 자료 전체를 읽고 한 주를 관통하는 흐름을 종합 분석하세요. 다음 JSON 형식으로만
답하세요(마크다운·설명 없이 JSON만):
{{
  "keywords": ["이번 주 반복적으로 등장한 핵심 키워드/테마, 중요도 순 최대 10개(단어 또는 짧은 구)"],
  "events": [{{"date":"YYYY-MM-DD 또는 기간","title":"실제 있었던 사건명","impact":"시장에 미친 영향 한 줄"}}],
  "week_summary": "한 주 시장 흐름을 관통하는 총평. 3~5개 문단, 문단 사이는 \\n\\n으로 구분. 마지막 문단은 결론 성격으로 마무리."
}}

제약:
- keywords는 원문에 실제로 반복 등장한 표현만 쓰세요(지어내지 말 것 — 이후
  원문에서 실제 등장 횟수를 프로그램으로 재검증합니다).
- events는 원문에 실제로 언급된 사건만, 날짜순으로 정렬하세요.
- 원문에 없는 수치나 사실을 지어내지 마세요.
"""


def _week_range(today):
    """오늘 기준 가장 최근(오늘 포함) 금요일과, 그 주의 월요일."""
    offset_to_friday = (today.weekday() - 4) % 7  # 4 = 금요일
    friday = today - datetime.timedelta(days=offset_to_friday)
    monday = friday - datetime.timedelta(days=4)
    return monday, friday


def _sources_block(items):
    parts = []
    for it in items:
        text = it.get("raw_content") or it.get("summary") or ""
        text = text[:4000]
        parts.append(f"[{it['date']} · {it['source']} — {it['title']}]\n{text}")
    return "\n\n".join(parts)


def _verify_keyword_counts(keywords, items):
    """LLM이 제안한 키워드가 실제 원문에 몇 건에서 등장했는지 재검증."""
    texts = [((it.get("title") or "") + " " + (it.get("summary") or "") + " "
              + (it.get("raw_content") or "")).lower() for it in items]
    counted = []
    for kw in keywords or []:
        k = (kw or "").strip().lower()
        if not k:
            continue
        cnt = sum(1 for t in texts if k in t)
        if cnt >= 1:
            counted.append((kw.strip(), cnt))
    counted.sort(key=lambda x: -x[1])
    return counted


def generate_digest(items, start, end, api_key=None, max_retries=2):
    import anthropic, time
    api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key or not items:
        return None
    client = anthropic.Anthropic(api_key=api_key)
    prompt = _PROMPT.format(start=start.isoformat(), end=end.isoformat(),
                             sources=_sources_block(items))
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = client.messages.create(
                model="claude-sonnet-5", max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in resp.content if b.type == "text")
            if resp.stop_reason == "max_tokens":
                raise RuntimeError("max_tokens에서 응답이 잘림")
            import re
            m = re.search(r"\{.*\}", text, re.DOTALL)
            data = json.loads(m.group(0)) if m else None
            if data:
                return data
            last_err = "빈 응답(JSON 파싱 실패)"
        except Exception as e:
            last_err = repr(e)[:150]
        if attempt < max_retries:
            print(f"  ! 주간 다이제스트 시도 {attempt+1} 실패({last_err}) — 재시도…")
            time.sleep(2 * (attempt + 1))
    print("  ! 주간 다이제스트 최종 실패:", last_err)
    return None


def build_email_body(start, end, items, digest, counted_keywords):
    by_source = {}
    for it in items:
        by_source[it["source"]] = by_source.get(it["source"], 0) + 1
    src_breakdown = " · ".join(f"{k} {v}건" for k, v in sorted(by_source.items(), key=lambda x: -x[1]))
    lines = [f"[주간 증시 브리핑] {start.isoformat()} ~ {end.isoformat()}", ""]

    if counted_keywords:
        lines.append("■ 이번 주 핵심 키워드")
        for i, (kw, cnt) in enumerate(counted_keywords[:10], 1):
            lines.append(f"  {i}. {kw} ({cnt}건 언급)")
        lines.append("")

    events = (digest or {}).get("events") or []
    if events:
        lines.append("■ 주요 이벤트")
        for ev in events:
            lines.append(f"  - {ev.get('date','')}: {ev.get('title','')} — {ev.get('impact','')}")
        lines.append("")

    summary = (digest or {}).get("week_summary")
    if summary:
        lines.append("■ 한 주 총평")
        lines.append(summary.strip())
        lines.append("")

    lines.append(f"수집 원문: 총 {len(items)}건 ({src_breakdown})")
    return "\n".join(lines)


_HTML_UP = "#cf202f"
_HTML_DN = "#0066cc"
_HTML_PRIMARY = "#1652f0"
_HTML_INK = "#0a0b0d"
_HTML_MUTED = "#6b7280"
_HTML_SOFT = "#f4f5f7"
_HTML_HAIR = "#e7e9ec"


def build_email_html(start, end, items, digest, counted_keywords):
    by_source = {}
    for it in items:
        by_source[it["source"]] = by_source.get(it["source"], 0) + 1
    src_breakdown = " · ".join(f"{k} {v}건" for k, v in sorted(by_source.items(), key=lambda x: -x[1]))

    max_cnt = max((c for _, c in counted_keywords[:10]), default=1)
    kw_rows = ""
    for i, (kw, cnt) in enumerate(counted_keywords[:10], 1):
        pct = max(int(cnt / max_cnt * 100), 6)
        kw_rows += f'''
        <tr>
          <td style="padding:9px 0;font-size:13px;color:{_HTML_MUTED};width:22px;font-weight:600;">{i}</td>
          <td style="padding:9px 0;font-size:14px;color:{_HTML_INK};font-weight:600;">{kw}</td>
          <td style="padding:9px 0;">
            <div style="background:{_HTML_HAIR};border-radius:100px;height:6px;width:160px;">
              <div style="background:{_HTML_PRIMARY};border-radius:100px;height:6px;width:{pct}%;"></div>
            </div>
          </td>
          <td style="padding:9px 0 9px 12px;font-size:12.5px;color:{_HTML_MUTED};white-space:nowrap;text-align:right;">{cnt}건</td>
        </tr>'''
    keywords_html = ""
    if kw_rows:
        keywords_html = f'''
        <tr><td style="padding:28px 28px 6px;">
          <div style="font-size:12px;font-weight:700;letter-spacing:.06em;color:{_HTML_PRIMARY};text-transform:uppercase;margin-bottom:12px;">이번 주 핵심 키워드</div>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tbody>{kw_rows}</tbody></table>
        </td></tr>'''

    events = (digest or {}).get("events") or []
    ev_rows = ""
    for ev in events:
        ev_rows += f'''
        <div style="padding:12px 0;border-bottom:1px solid {_HTML_HAIR};">
          <div style="font-size:12px;font-family:monospace,monospace;color:{_HTML_PRIMARY};font-weight:700;margin-bottom:3px;">{ev.get('date','')}</div>
          <div style="font-size:14px;color:{_HTML_INK};font-weight:600;line-height:1.5;">{ev.get('title','')}</div>
          <div style="font-size:13px;color:{_HTML_MUTED};margin-top:2px;line-height:1.5;">{ev.get('impact','')}</div>
        </div>'''
    events_html = ""
    if ev_rows:
        events_html = f'''
        <tr><td style="padding:28px 28px 6px;">
          <div style="font-size:12px;font-weight:700;letter-spacing:.06em;color:{_HTML_PRIMARY};text-transform:uppercase;margin-bottom:8px;">주요 이벤트</div>
          <div>{ev_rows}</div>
        </td></tr>'''

    summary = ((digest or {}).get("week_summary") or "").strip()
    para_lines = [p.strip() for p in summary.split("\n") if p.strip()]
    summary_html = ""
    if para_lines:
        body_paras = "".join(
            f'<p style="margin:0 0 14px;font-size:14.5px;line-height:1.75;color:#1f2328;">{p}</p>'
            for p in para_lines[:-1])
        concl = (f'<p style="margin:14px 0 0;padding-top:14px;border-top:1px solid {_HTML_HAIR};'
                 f'font-size:14.5px;line-height:1.75;color:{_HTML_INK};font-weight:600;">{para_lines[-1]}</p>')
        summary_html = f'''
        <tr><td style="padding:28px 28px 6px;">
          <div style="font-size:12px;font-weight:700;letter-spacing:.06em;color:{_HTML_PRIMARY};text-transform:uppercase;margin-bottom:12px;">한 주 총평</div>
          <div style="background:{_HTML_SOFT};border-radius:14px;padding:20px 22px;">{body_paras}{concl}</div>
        </td></tr>'''

    return f'''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;padding:0;background:#eef0f3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Pretendard,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef0f3;padding:28px 12px;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:20px;overflow:hidden;">
  <tr><td style="background:{_HTML_INK};padding:30px 28px;">
    <div style="font-size:11.5px;font-weight:700;letter-spacing:.08em;color:#8b93a0;text-transform:uppercase;margin-bottom:8px;">Weekly Digest</div>
    <div style="font-size:22px;font-weight:700;color:#ffffff;">주간 증시 브리핑</div>
    <div style="font-size:13px;color:#9aa3b0;margin-top:6px;">{start.isoformat()} ~ {end.isoformat()}</div>
  </td></tr>
  {keywords_html}
  {events_html}
  {summary_html}
  <tr><td style="padding:22px 28px 28px;">
    <div style="border-top:1px solid {_HTML_HAIR};padding-top:16px;font-size:12px;color:{_HTML_MUTED};line-height:1.6;">
      수집 원문 총 {len(items)}건 · {src_breakdown}<br>
      이 다이제스트는 원문을 종합한 AI 생성 요약이며, 키워드 등장 횟수는 원문에서 실제로 재검증한 값입니다.
    </div>
  </td></tr>
</table>
</td></tr>
</table>
</body></html>'''


def _marker_path(week_id):
    return os.path.join(MARKER_DIR, f"weekly_{week_id}.done")


def run(now_sgt=None, dry_run=False):
    now_sgt = now_sgt or datetime.datetime.now(SGT)
    today = now_sgt.date()
    monday, friday = _week_range(today)
    week_id = f"{monday.isocalendar()[0]}-W{monday.isocalendar()[1]:02d}"

    if os.path.exists(_marker_path(week_id)):
        print(f"[weekly] 이미 발송됨 — {week_id}")
        return None

    import sources
    items = sources.list_week_sources(monday, friday)
    print(f"[weekly] {monday} ~ {friday} 수집 원문 {len(items)}건")
    if not items:
        print("[weekly] 수집된 원문이 없어 건너뜁니다.")
        return None

    digest = generate_digest(items, monday, friday)
    counted = _verify_keyword_counts((digest or {}).get("keywords"), items)
    body = build_email_body(monday, friday, items, digest, counted)
    html = build_email_html(monday, friday, items, digest, counted)
    subject = f"[주간 증시 브리핑] {monday.isoformat()} ~ {friday.isoformat()} 핵심 키워드 & 이벤트"

    if dry_run:
        print(body)
        return dict(subject=subject, body=body, html=html)

    os.makedirs(MARKER_DIR, exist_ok=True)
    with open(_marker_path(week_id), "w", encoding="utf-8") as f:
        json.dump({"at": now_sgt.isoformat()}, f, ensure_ascii=False)

    import delivery
    res = delivery.send_email(subject, body, [], html_body=html)
    print("  → 이메일 발송 완료:", res)
    return res


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
