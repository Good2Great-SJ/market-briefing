import io
import json
import os
import re
from datetime import datetime, timezone

import pdfplumber
import requests
import yaml
from anthropic import Anthropic
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from db.db import insert_consensus_report, report_exists

load_dotenv()

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) naver-blog-kakao-notifier"}
LIST_URL = "https://finance.naver.com/research/company_list.naver"
DETAIL_URL = "https://finance.naver.com/research/company_read.naver"

FIN_BLOCK_PATTERN = re.compile(
    r"(투자지표|Financial Data|Consensus Data|영업실적).{0,400}?(매출액.{0,300}?영업이익.{0,300})",
    re.DOTALL,
)

OPTIMISTIC_KEYWORDS = ["buy", "매수", "strongbuy", "strong buy", "outperform", "overweight", "positive"]
PESSIMISTIC_KEYWORDS = ["sell", "매도", "underweight", "reduce", "negative", "비중축소"]

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")


def _load_consensus_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("consensus") or {}


def classify_stance(opinion_raw: str) -> str:
    if not opinion_raw:
        return "중립"
    text = opinion_raw.strip().lower()
    if any(kw in text for kw in OPTIMISTIC_KEYWORDS):
        return "낙관"
    if any(kw in text for kw in PESSIMISTIC_KEYWORDS):
        return "비관"
    return "중립"


def _parse_date(date_str: str) -> str:
    """'26.07.08' -> '2026-07-08'"""
    d = datetime.strptime(date_str, "%y.%m.%d")
    return d.strftime("%Y-%m-%d")


def fetch_report_list(item_code: str, since_date: str | None = None, max_pages: int = 30) -> list[dict]:
    """종목분석 리포트 목록을 페이지네이션하며 조회한다.

    since_date(YYYY-MM-DD)를 넘기면 그 이전 리포트가 나오는 순간 조회를 중단한다.
    """
    since_dt = datetime.strptime(since_date, "%Y-%m-%d") if since_date else None
    reports = []
    page = 1

    while page <= max_pages:
        resp = requests.get(
            LIST_URL,
            params={"searchType": "itemCode", "itemCode": item_code, "keyword": "", "page": page},
            headers=HEADERS,
            timeout=10,
        )
        resp.encoding = "euc-kr"
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.select_one("table.type_1")
        if table is None:
            break
        rows = table.select("tr")

        found = 0
        stop = False
        for row in rows:
            title_a = row.select_one("td a[href*='company_read.naver']")
            if not title_a:
                continue
            href = title_a["href"]
            nid_match = re.search(r"nid=(\d+)", href)
            if not nid_match:
                continue
            tds = row.select("td")
            raw_date = tds[4].get_text(strip=True) if len(tds) > 4 else ""
            try:
                date_iso = _parse_date(raw_date)
            except ValueError:
                continue

            found += 1
            if since_dt and datetime.strptime(date_iso, "%Y-%m-%d") < since_dt:
                stop = True
                continue

            reports.append(
                {
                    "nid": nid_match.group(1),
                    "title": title_a.get_text(strip=True),
                    "broker": tds[2].get_text(strip=True) if len(tds) > 2 else "",
                    "date": date_iso,
                }
            )

        if stop or found == 0:
            break
        page += 1

    return reports


def fetch_report_detail(nid: str) -> dict:
    resp = requests.get(DETAIL_URL, params={"nid": nid}, headers=HEADERS, timeout=10)
    resp.encoding = "euc-kr"
    soup = BeautifulSoup(resp.text, "html.parser")

    target_price = None
    opinion_raw = ""
    info = soup.select_one(".view_info_1")
    if info:
        money = info.select_one("em.money")
        coment = info.select_one("em.coment")
        if money:
            price_text = money.get_text(strip=True).replace(",", "")
            target_price = int(price_text) if price_text.isdigit() else None
        opinion_raw = coment.get_text(strip=True) if coment else ""

    pdf_a = soup.select_one("a.con_link[href$='.pdf']")
    pdf_url = pdf_a["href"] if pdf_a else None

    return {"target_price": target_price, "opinion_raw": opinion_raw, "pdf_url": pdf_url}


def _extract_pdf_text(pdf_url: str, max_pages: int = 2) -> str:
    resp = requests.get(pdf_url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    parts = []
    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        for p in pdf.pages[:max_pages]:
            parts.append(p.extract_text() or "")
    return "\n".join(parts)


def _isolate_financial_block(full_text: str) -> str:
    m = FIN_BLOCK_PATTERN.search(full_text)
    if m:
        start = m.start()
        return full_text[start : start + 700]
    return full_text[:1800]


def _extract_estimates_with_claude(client: Anthropic, model: str, block_text: str) -> dict | None:
    if len(block_text.strip()) < 100:
        return None

    prompt = f"""\
아래는 증권사 리포트 PDF에서 추출한 실적 추정치 표 텍스트다.
연도별 매출액과 영업이익 추정치(단위 무관, 원문 그대로)를 찾아 JSON으로만 답해라.
표를 찾을 수 없거나 수치가 없으면 {{"found": false}}로 답해라.

반드시 아래 형식:
{{"found": true, "unit": "십억원 또는 억원 등 원문 단위", "years": {{"2026": {{"revenue": 750289.7, "operating_profit": 391641.5}}, "2027": {{"revenue": ..., "operating_profit": ...}}}}}}

[텍스트]
{block_text}
"""
    try:
        message = client.messages.create(
            model=model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = next(b for b in message.content if b.type == "text").text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text)
        return result if result.get("found") else None
    except Exception:
        return None


def extract_financial_estimates(pdf_url: str | None, client: Anthropic, model: str) -> tuple[dict | None, str]:
    """PDF에서 실적 추정치를 추출한다. (추정치 or None, pdf_status) 튜플을 반환한다.

    pdf_status: 'ok' | 'no_pdf' | 'image_pdf' | 'parse_failed'
    """
    if not pdf_url:
        return None, "no_pdf"

    try:
        full_text = _extract_pdf_text(pdf_url)
    except Exception:
        return None, "parse_failed"

    if len(full_text.strip()) < 150:
        return None, "image_pdf"

    block = _isolate_financial_block(full_text)
    estimate = _extract_estimates_with_claude(client, model, block)
    if estimate is None:
        return None, "parse_failed"
    return estimate, "ok"


def collect_new_reports(stock_code: str, stock_name: str, since_date: str | None = None) -> list[dict]:
    """신규 리포트를 수집해 DB에 저장하고, 새로 저장된 리포트 목록을 반환한다."""
    cfg = _load_consensus_config()
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"].strip())
    model = cfg.get("model", "claude-sonnet-5")

    reports = fetch_report_list(stock_code, since_date=since_date)
    new_reports = []

    for r in reports:
        if report_exists(r["nid"]):
            continue

        detail = fetch_report_detail(r["nid"])
        estimate, pdf_status = extract_financial_estimates(detail["pdf_url"], client, model)

        fiscal_year_current = None
        revenue_estimate_current = None
        operating_profit_estimate_current = None
        fiscal_year_next = None
        revenue_estimate_next = None
        operating_profit_estimate_next = None
        estimate_unit = None
        if estimate:
            current_year = datetime.now().year
            years = estimate.get("years", {})
            estimate_unit = estimate.get("unit")

            current_key = str(current_year) if str(current_year) in years else None
            next_key = str(current_year + 1) if str(current_year + 1) in years else None

            if current_key:
                y = years[current_key]
                fiscal_year_current = current_key
                revenue_estimate_current = y.get("revenue")
                operating_profit_estimate_current = y.get("operating_profit")
            if next_key:
                y = years[next_key]
                fiscal_year_next = next_key
                revenue_estimate_next = y.get("revenue")
                operating_profit_estimate_next = y.get("operating_profit")

        row = {
            "nid": r["nid"],
            "stock_code": stock_code,
            "stock_name": stock_name,
            "broker": r["broker"],
            "report_date": r["date"],
            "title": r["title"],
            "target_price": detail["target_price"],
            "opinion_raw": detail["opinion_raw"],
            "fiscal_year_current": fiscal_year_current,
            "revenue_estimate_current": revenue_estimate_current,
            "operating_profit_estimate_current": operating_profit_estimate_current,
            "fiscal_year_next": fiscal_year_next,
            "revenue_estimate_next": revenue_estimate_next,
            "operating_profit_estimate_next": operating_profit_estimate_next,
            "estimate_unit": estimate_unit,
            "pdf_status": pdf_status,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }
        insert_consensus_report(row)
        new_reports.append(row)

    return new_reports
