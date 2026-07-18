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


def build_email_body(session, ref, narr, summary, mc, link_url=""):
    """이메일 본문. 총평(소스별 분리, 전문) + 핵심 지표 + 리포트 링크."""
    label = "미국 증시 마감" if session == "us" else "한국 증시 마감"
    lines = [f"[{label} 브리핑] {ref}", ""]
    bd = narr.get("butterdaddy_analysis") if narr else None
    jg = narr.get("jeungsi_analysis") if narr else None
    if bd or jg:
        if bd:
            lines.append("■ 버터대디 총평")
            lines.append(bd.strip())
            lines.append("")
        if jg:
            lines.append("■ 증시각도기 총평")
            lines.append(jg.strip())
            lines.append("")
    elif narr and narr.get("overview"):
        lines.append(narr["overview"].strip())
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
    if "KOSPI" in mc:
        lines.append(f"코스피 시총 5년내 {mc['KOSPI']['pct5']:.0f}% 수준 "
                     f"(버핏지수 {mc.get('buffett', float('nan')):.0f}%)")
    if narr and narr.get("calendar"):
        lines.append("")
        lines.append("다가오는 일정")
        for c in narr["calendar"]:
            lines.append(f"  - {c.get('date','')} {c.get('event','')}")
    if link_url:
        lines.append("")
        lines.append(f"웹에서 보기: {link_url}")
    lines.append("")
    lines.append("첨부된 PDF에서 전체 리포트를 확인하세요.")
    return "\n".join(lines)


def send_email(subject, body_text, pdf_paths, to_addr=None):
    """
    PDF를 첨부해 이메일로 발송한다. .env에 아래 값이 필요:
      EMAIL_SMTP_HOST (기본 smtp.gmail.com), EMAIL_SMTP_PORT (기본 587)
      EMAIL_SENDER, EMAIL_APP_PASSWORD, EMAIL_RECEIVER
    Gmail 기준 EMAIL_APP_PASSWORD는 일반 비밀번호가 아닌 앱 비밀번호
    (myaccount.google.com/apppasswords)가 필요하다.
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

    for p in pdf_paths:
        p = pathlib.Path(p)
        with open(p, "rb") as f:
            msg.add_attachment(f.read(), maintype="application", subtype="pdf", filename=p.name)

    if port == 465:
        with smtplib.SMTP_SSL(host, port) as s:
            s.login(sender, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port) as s:
            s.starttls()
            s.login(sender, password)
            s.send_message(msg)
    return {"sent_to": receiver, "attachments": [pathlib.Path(p).name for p in pdf_paths]}
