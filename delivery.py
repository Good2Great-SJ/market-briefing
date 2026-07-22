# -*- coding: utf-8 -*-
"""
배포 모듈
  · html_to_pdf()   : playwright(chromium)로 HTML → PDF
  · send_email()    : PDF 첨부 + 리포트 링크를 이메일로 발송
"""
import os, pathlib
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def html_to_pdf(html_path, pdf_path=None):
    from playwright.sync_api import sync_playwright
    src = pathlib.Path(html_path).resolve().as_uri()
    pdf_path = pdf_path or str(pathlib.Path(html_path).with_suffix(".pdf"))
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(src, wait_until="networkidle")
        pg.emulate_media(color_scheme="light")
        # 가로(landscape) — 스캔 테이블(8개 컬럼)이 세로 A4보다 가로 폭에서 안 잘림
        pg.pdf(path=pdf_path, format="A4", landscape=True, print_background=True,
               margin={"top": "10mm", "bottom": "10mm", "left": "8mm", "right": "8mm"})
        b.close()
    return pdf_path


def _spaced_paragraphs(text):
    """단락 사이에 빈 줄을 넣어 읽기 편하게 만든다.

    narr의 각 텍스트 필드는 원래 \\n 하나로만 단락이 구분돼 있어(HTML 쪽은
    _paragraphs()가 이걸 <p> 태그로 바꿔 시각적 여백을 만들지만) 텍스트 메일에서는
    줄바꿈이 단락처럼 안 보이고 다 붙어 있는 것처럼 읽혔다 — 빈 줄로 재구성한다.
    """
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    return "\n\n".join(parts)


def build_email_body(title, ref, narr, summary, mc, link_url="", events=None):
    """이메일 본문. 총평(소스별 분리, 전문) + 핵심 지표 + 리포트 링크.

    title: 제목 줄에 그대로 쓸 리포트 제목(예: "한국 증시 마감 브리핑" 또는
    거래일 공백 시의 "N월 N일(월) 한국증시 장전 리포트"). session에서 다시
    유추하지 않는 이유는, 예전엔 여기서 session만 보고 "미국/한국 증시 마감"으로
    고정해 만들어서 장전 리포트처럼 제목이 달라지는 경우 메일 제목(subject)과
    본문 첫 줄이 서로 다르게 나가던 문제가 있었기 때문이다.

    events: narr의 calendar 필드 대신 쓰는, events.py가 만든 확정 일정 목록
    (FOMC·금통위·만기일·실적발표 등). 총평 원문 언급 여부와 무관하게 항상
    일관되게 표시하기 위해 narr와 분리했다.
    """
    lines = [f"[{title}] {ref}", ""]
    bd = narr.get("butterdaddy_analysis") if narr else None
    jg = narr.get("jeungsi_analysis") if narr else None
    if bd or jg:
        if bd:
            lines.append("■ 버터대디 총평")
            lines.append(_spaced_paragraphs(bd))
            lines.append("")
        if jg:
            lines.append("■ 증시각도기 총평")
            lines.append(_spaced_paragraphs(jg))
            lines.append("")
    elif narr and narr.get("overview"):
        lines.append(_spaced_paragraphs(narr["overview"]))
        lines.append("")
    else:
        lines.append(f"상승 {summary['n_up']} / 하락 {summary['n_dn']} · "
                     f"정배열 {summary['arr_g']} / 역배열 {summary['arr_r']}")
        lines.append("")
    if narr and narr.get("checkpoints"):
        lines.append("체크포인트")
        for c in narr["checkpoints"]:
            lines.append(f"  - {c}")
        lines.append("")
    if narr and narr.get("news"):
        lines.append("시장 영향 뉴스")
        for n in narr["news"]:
            lines.append(f"  - {n.get('title','')}")
            if n.get("impact"):
                lines.append(f"    → {n['impact']}")
        lines.append("")
    if "KOSPI" in mc:
        lines.append(f"코스피 시총 5년내 {mc['KOSPI']['pct5']:.0f}% 수준 "
                     f"(버핏지수 {mc.get('buffett', float('nan')):.0f}%)")
    if events:
        lines.append("")
        lines.append("체크해야 할 주요 증시 이벤트")
        for e in events:
            lines.append(f"  - {e.get('date','')} {e.get('event','')}")
    if link_url:
        lines.append("")
        lines.append(f"웹에서 전체 리포트 보기: {link_url}")
    return "\n".join(lines)


_CB_INK = "#0a0b0d"
_CB_BODY = "#5b616e"
_CB_MUTED = "#7c828a"
_CB_HAIR = "#dee1e6"
_CB_SOFT = "#f7f7f7"
_CB_PRIMARY = "#0052ff"
_CB_UP = "#cf202f"


def _html_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _html_paragraphs(text):
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    return "".join(
        f'<p style="margin:0 0 14px;font-size:14.5px;line-height:1.7;color:{_CB_INK}">{_html_escape(p)}</p>'
        for p in parts
    )


def build_email_html(title, ref, narr, summary, mc, link_url="", events=None):
    """리포트 웹페이지와 동일한 코인베이스 톤(흰 배경, #0052ff 포인트, 카드형
    섹션)으로 이메일 HTML 버전을 만든다. send_email(html_body=...)에 넘기면
    지원 클라이언트에서는 이 버전이, 미지원 클라이언트에서는 build_email_body의
    텍스트 버전이 자동으로 대체 표시된다."""
    sections = []

    bd = narr.get("butterdaddy_analysis") if narr else None
    jg = narr.get("jeungsi_analysis") if narr else None

    def _src_card(label, text):
        return f'''<tr><td style="padding:0 0 16px">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="background:#fff;border:1px solid {_CB_HAIR};border-radius:14px">
            <tr><td style="padding:20px 22px">
              <div style="font-size:12px;font-weight:700;letter-spacing:.04em;color:{_CB_PRIMARY};
                          text-transform:uppercase;margin-bottom:10px">{_html_escape(label)}</div>
              {_html_paragraphs(text)}
            </td></tr>
          </table></td></tr>'''

    if bd or jg:
        if bd:
            sections.append(_src_card("버터대디 총평", bd))
        if jg:
            sections.append(_src_card("증시각도기 총평", jg))
    elif narr and narr.get("overview"):
        sections.append(_src_card("오늘의 총평", narr["overview"]))
    else:
        sections.append(_src_card(
            "오늘의 총평",
            f"상승 {summary['n_up']} / 하락 {summary['n_dn']} · "
            f"정배열 {summary['arr_g']} / 역배열 {summary['arr_r']}"))

    if narr and narr.get("checkpoints"):
        items = "".join(
            f'<li style="margin:0 0 8px;font-size:14px;line-height:1.6;color:{_CB_INK}">{_html_escape(c)}</li>'
            for c in narr["checkpoints"])
        sections.append(f'''<tr><td style="padding:0 0 16px">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="background:{_CB_SOFT};border-radius:14px">
            <tr><td style="padding:18px 22px">
              <div style="font-size:12px;font-weight:700;letter-spacing:.04em;color:{_CB_MUTED};
                          text-transform:uppercase;margin-bottom:10px">체크포인트</div>
              <ul style="margin:0;padding-left:18px">{items}</ul>
            </td></tr>
          </table></td></tr>''')

    if narr and narr.get("news"):
        rows = "".join(
            f'''<div style="padding:10px 0;border-bottom:1px solid {_CB_HAIR}">
              <div style="font-size:13.5px;font-weight:600;color:{_CB_INK}">{_html_escape(n.get('title',''))}</div>
              {f'<div style="font-size:12.5px;color:{_CB_MUTED};margin-top:3px">{_html_escape(n["impact"])}</div>' if n.get('impact') else ''}
            </div>''' for n in narr["news"])
        sections.append(f'''<tr><td style="padding:0 0 16px">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="background:#fff;border:1px solid {_CB_HAIR};border-radius:14px">
            <tr><td style="padding:18px 22px 4px">
              <div style="font-size:12px;font-weight:700;letter-spacing:.04em;color:{_CB_MUTED};
                          text-transform:uppercase;margin-bottom:6px">시장 영향 뉴스</div>
              {rows}
            </td></tr>
          </table></td></tr>''')

    if "KOSPI" in mc:
        sections.append(f'''<tr><td style="padding:0 0 16px;font-size:13.5px;color:{_CB_BODY}">
          코스피 시총 5년내 <b style="color:{_CB_INK}">{mc['KOSPI']['pct5']:.0f}%</b> 수준
          (버핏지수 {mc.get('buffett', float('nan')):.0f}%)</td></tr>''')

    if events:
        rows = "".join(
            f'''<tr>
              <td style="padding:7px 0;border-bottom:1px solid {_CB_HAIR};font-size:13px;
                         color:{_CB_PRIMARY};font-weight:600;white-space:nowrap;vertical-align:top">
                {_html_escape(e.get('date',''))}</td>
              <td style="padding:7px 0 7px 12px;border-bottom:1px solid {_CB_HAIR};font-size:13px;color:{_CB_INK}">
                {_html_escape(e.get('event',''))}</td>
            </tr>''' for e in events)
        sections.append(f'''<tr><td style="padding:0 0 16px">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="background:#fff;border:1px solid {_CB_HAIR};border-radius:14px">
            <tr><td style="padding:18px 22px">
              <div style="font-size:12px;font-weight:700;letter-spacing:.04em;color:{_CB_MUTED};
                          text-transform:uppercase;margin-bottom:10px">체크해야 할 주요 증시 이벤트</div>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table>
            </td></tr>
          </table></td></tr>''')

    cta = ""
    if link_url:
        # <a> 태그에 직접 padding/border-radius를 주면 클라이언트에 따라(특히
        # 일부 웹메일) 안 먹혀서 버튼이 찌그러지거나 글자가 잘려 보이는 경우가
        # 있다 — 배경·모양은 <td>에 주고 <a>는 그 안을 꽉 채우기만 하는
        # "안전한 버튼" 패턴으로 바꿔 어느 클라이언트에서도 크기가 안정적이게 함.
        safe_url = link_url.replace('&', '&amp;')
        # display:block으로 했더니 <a>가 부모 폭에 맞춰 카드 전체 너비로 늘어나
        # 버튼이 과도하게 커 보였다 — inline-block으로 바꿔 내용 크기에 맞게
        # 딱 맞는 크기로 렌더링되게 함(그래도 padding/줄바꿈 방지는 유지).
        cta = f'''<tr><td style="padding:8px 0 0" align="center">
          <table role="presentation" cellpadding="0" cellspacing="0" align="center" style="margin:0 auto">
            <tr><td style="background:{_CB_PRIMARY};border-radius:10px" align="center">
              <a href="{safe_url}" style="display:inline-block;color:#fff;font-size:14px;font-weight:600;
                 text-decoration:none;padding:13px 26px;white-space:nowrap">
                웹에서 전체 리포트 보기 →</a>
            </td></tr>
          </table>
        </td></tr>'''

    return f'''<!doctype html><html><body style="margin:0;padding:0;background:{_CB_SOFT};
      font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Malgun Gothic',sans-serif">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_CB_SOFT}">
        <tr><td align="center" style="padding:32px 16px">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px">
            <tr><td style="padding:0 4px 22px">
              <div style="font-size:12px;font-weight:700;letter-spacing:.06em;color:{_CB_PRIMARY};
                          text-transform:uppercase;margin-bottom:6px">📖 Good To Great</div>
              <div style="font-size:22px;font-weight:700;letter-spacing:-.01em;color:{_CB_INK}">
                {_html_escape(title)}</div>
              <div style="font-size:13px;color:{_CB_MUTED};margin-top:4px">{_html_escape(ref)}</div>
            </td></tr>
            {"".join(sections)}
            {cta}
            <tr><td style="padding:24px 4px 0;font-size:11.5px;color:{_CB_MUTED};
                          border-top:1px solid {_CB_HAIR};margin-top:8px">
              자동 생성된 리포트입니다 · yfinance · FinanceDataReader · Claude
            </td></tr>
          </table>
        </td></tr>
      </table></body></html>'''


def send_email(subject, body_text, pdf_paths, to_addr=None, html_body=None):
    """
    PDF를 첨부해 이메일로 발송한다. .env에 아래 값이 필요:
      EMAIL_SMTP_HOST (기본 smtp.gmail.com), EMAIL_SMTP_PORT (기본 587)
      EMAIL_SENDER, EMAIL_APP_PASSWORD, EMAIL_RECEIVER
    Gmail 기준 EMAIL_APP_PASSWORD는 일반 비밀번호가 아닌 앱 비밀번호
    (myaccount.google.com/apppasswords)가 필요하다.
    html_body를 주면 HTML 버전을 함께 넣는다(구버전 클라이언트용 body_text는
    항상 폴백으로 포함).
    """
    import smtplib
    from email.message import EmailMessage

    host = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("EMAIL_SMTP_PORT", "587"))
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_APP_PASSWORD")
    receiver = to_addr or os.getenv("EMAIL_RECEIVER")

    if not sender or not password or not receiver:
        raise RuntimeError(
            "이메일 발송 설정이 없습니다. market-briefing/.env에 "
            "EMAIL_SENDER, EMAIL_APP_PASSWORD, EMAIL_RECEIVER를 채워주세요."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = receiver
    msg.set_content(body_text)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    for p in pdf_paths:
        p = pathlib.Path(p)
        with open(p, "rb") as f:
            msg.add_attachment(f.read(), maintype="application", subtype="pdf", filename=p.name)

    # GitHub Actions 러너 IP에서 Gmail SMTP로의 연결이 일시적으로 끊기거나
    # 거부되는 경우가 있다(클라우드/데이터센터 IP 대상 일시적 차단은 흔함 —
    # 같은 계정의 다른 프로젝트에서 YouTube 안티봇에 GH Actions IP가 막힌
    # 전례도 있음). 재시도 없이 한 번 실패하면 그날 이메일이 통째로 누락되므로
    # 지수 백오프로 재시도한다.
    import time
    last_err = None
    for attempt in range(3):
        try:
            if port == 465:
                with smtplib.SMTP_SSL(host, port, timeout=30) as s:
                    s.login(sender, password)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=30) as s:
                    s.starttls()
                    s.login(sender, password)
                    s.send_message(msg)
            return {"sent_to": receiver, "attachments": [pathlib.Path(p).name for p in pdf_paths]}
        except Exception as e:
            last_err = e
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
    raise last_err
