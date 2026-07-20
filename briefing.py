# -*- coding: utf-8 -*-
"""
데일리 마켓 브리핑 생성기 (버터대디 루틴 자동화) — Coinbase 디자인
  · 세션        : 미국증시 마감(us) / 한국증시 마감(kr) 각각 생성
  · 상단 총평   : Claude API + 웹서치 (장 흐름·체크포인트·뉴스·일정)
  · 데이터      : yfinance + FinanceDataReader + 네이버 증시자금동향
  · 심화 분석   : 코스피/코스닥 시총 수준, 시장폭, 장단기 금리차
  · 출력        : 자체완결형 HTML  +  PDF(playwright)

사용:
  python briefing.py us      # 미국 증시 마감 브리핑
  python briefing.py kr      # 한국 증시 마감 브리핑
  python briefing.py         # KST 시각으로 자동 판별
"""
import warnings, io, base64, datetime, os, sys
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle

import universe as U
import analytics
import narrative
import themes
import sources as srcmod
import ai_tech

for _f in ("Malgun Gothic", "Apple SD Gothic Neo", "NanumGothic", "DejaVu Sans"):
    try:
        plt.rcParams["font.family"] = _f
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False
KST = datetime.timezone(datetime.timedelta(hours=9))


# ══════════════════════════════════════════════════════════════
# 1. 데이터 수집
# ══════════════════════════════════════════════════════════════
def fetch_yf(tickers):
    import yfinance as yf
    syms = [t for t, _ in tickers]
    raw = yf.download(syms, period="1y", interval="1d",
                      auto_adjust=True, progress=False, threads=True)
    out = {}
    for t in syms:
        try:
            df = pd.DataFrame({"Close": raw["Close"][t], "Open": raw["Open"][t],
                               "High": raw["High"][t], "Low": raw["Low"][t]}).dropna()
            if len(df) >= 30:
                out[t] = df
        except Exception:
            pass
    return out


def fetch_fdr(items):
    import FinanceDataReader as fdr
    start = (datetime.date.today() - datetime.timedelta(days=420)).isoformat()
    out = {}
    for code, _ in items:
        try:
            df = fdr.DataReader(code, start)
            keep = {"Close": df["Close"], "Open": df["Open"], "High": df["High"], "Low": df["Low"]}
            if "Amount" in df.columns:
                keep["Amount"] = df["Amount"]
            out[code] = pd.DataFrame(keep).dropna(subset=["Close"])
        except Exception:
            pass
    return out


def fetch_kr_money():
    import requests
    h = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"}
    r = requests.get("https://finance.naver.com/sise/sise_deposit.naver",
                     headers=h, timeout=20)
    r.encoding = "euc-kr"
    t = pd.read_html(io.StringIO(r.text))[0]
    cols = ["날짜", "고객예탁금", "예탁금증감", "신용융자잔고", "신용증감",
            "주식형", "주식형증감", "채권형", "채권형증감", "MMF", "MMF증감"]
    t.columns = cols[:len(t.columns)]
    return t.dropna(subset=["날짜"]).reset_index(drop=True)


# ══════════════════════════════════════════════════════════════
# 2. 지표 계산
# ══════════════════════════════════════════════════════════════
def compute(df):
    c = df["Close"].astype(float)
    close, prev = c.iloc[-1], c.iloc[-2]
    chg = (close / prev - 1) * 100
    ma = {p: (c.rolling(p).mean().iloc[-1] if len(c) >= p else np.nan)
          for p in (10, 20, 50, 200)}
    gap = {p: ((close / ma[p] - 1) * 100 if ma[p] == ma[p] else np.nan) for p in ma}
    seq = [ma[10], ma[20], ma[50], ma[200]]
    if all(x == x for x in seq):
        if ma[10] > ma[20] > ma[50] > ma[200] and close > ma[10]:
            arr = "정배열"
        elif ma[10] < ma[20] < ma[50] < ma[200]:
            arr = "역배열"
        else:
            arr = "혼조"
    else:
        arr = "-"
    hi, lo = df["High"].max(), df["Low"].min()
    from_hi = (close / hi - 1) * 100
    from_lo = (close / lo - 1) * 100
    tags, prev_c = [], c.iloc[-2]
    for p, label in ((10, "10일선"), (50, "50일선"), (200, "200일선")):
        m = ma[p]; pm = c.rolling(p).mean().iloc[-2] if len(c) >= p + 1 else np.nan
        if m == m and pm == pm:
            if prev_c < pm and close > m:
                tags.append(f"{label} 회복")
            elif prev_c > pm and close < m:
                tags.append(f"{label} 이탈")
    if ma[200] == ma[200] and abs(gap[200]) <= 1.5:
        tags.append("200일선 테스트")
    if from_hi >= -2:
        tags.append("신고가 근접")
    if from_lo <= 3:
        tags.append("신저가 근접")
    return dict(close=close, prev=prev, chg=chg, ma=ma, gap=gap, arr=arr,
                from_hi=from_hi, from_lo=from_lo, tags=tags)


# ══════════════════════════════════════════════════════════════
# 3. 차트 (Coinbase 팔레트)
# ══════════════════════════════════════════════════════════════
_CANDLE_UP = "#cf202f"    # 상승(양봉) — 사이트 전체 --up 색상과 통일
_CANDLE_DN = "#0066cc"    # 하락(음봉) — 사이트 전체 --dn 색상과 통일


def chart_b64(df, name, n=130):
    o = df["Open"].astype(float).tail(n)
    h = df["High"].astype(float).tail(n)
    l = df["Low"].astype(float).tail(n)
    c = df["Close"].astype(float).tail(n)
    idx = c.index
    x = mdates.date2num(idx.to_pydatetime())
    width = (x[-1] - x[0]) / max(len(x), 1) * 0.62 if len(x) > 1 else 0.6

    fig, ax = plt.subplots(figsize=(4.7, 2.3), dpi=115)
    fig.patch.set_facecolor("#fff"); ax.set_facecolor("#fff")
    for xi, oi, hi, li, ci in zip(x, o, h, l, c):
        color = _CANDLE_UP if ci >= oi else _CANDLE_DN
        ax.plot([xi, xi], [li, hi], color=color, lw=.6, zorder=3, solid_capstyle="round")
        lower, height = min(oi, ci), abs(ci - oi)
        if height == 0:
            height = hi * 0.0008  # 도지(시가=종가)도 얇은 선으로 보이게
        ax.add_patch(Rectangle((xi - width / 2, lower), width, height,
                                facecolor=color, edgecolor=color, lw=0, zorder=4))
    for p, col in ((10, "#7c828a"), (50, "#0052ff"), (200, "#8a5a00")):
        full = df["Close"].astype(float).rolling(p).mean().tail(n)
        if full.notna().any():
            ax.plot(idx, full, color=col, lw=1.1, alpha=.95, label=f"MA{p}", zorder=5)
    ax.xaxis_date()
    ax.set_title(name, fontsize=11, fontweight="600", color="#0a0b0d", pad=6, loc="left")
    ax.legend(fontsize=6.6, loc="upper left", frameon=False, ncol=3,
              handlelength=1.1, columnspacing=.9, labelcolor="#7c828a")
    ax.grid(True, axis="y", alpha=1, lw=.7, color="#eef0f3")
    ax.tick_params(labelsize=6.8, colors="#7c828a", length=0)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m월"))
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#dee1e6")
    fig.tight_layout(pad=.4)
    buf = io.BytesIO(); fig.savefig(buf, format="png", facecolor="#fff")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


# ══════════════════════════════════════════════════════════════
# 4. HTML 헬퍼
# ══════════════════════════════════════════════════════════════
def gap_html(g):
    if g != g:
        return '<span class="mut">–</span>'
    cls, arr = ("up", "▲") if g >= 0 else ("dn", "▼")
    return f'<span class="{cls}">{arr}{abs(g):.1f}%</span>'


def chg_html(g):
    if g != g:
        return '<span class="mut">–</span>'
    cls = "up" if g >= 0 else "dn"
    return f'<span class="{cls}">{"+" if g >= 0 else ""}{g:.2f}%</span>'


def bps_html(close, prev):
    """
    금리(수익률) 티커 전용 — %변화율 대신(또는 병기) bp(basis point) 변동을 표시.
    yfinance 금리 티커(^TNX 등)는 값 자체가 이미 %단위(예: 4.54=4.54%)이므로
    close-prev의 차이(퍼센트포인트)에 100을 곱하면 bp 변동이 된다.
    """
    if close != close or prev != prev:
        return '<span class="mut">–</span>'
    bp = (close - prev) * 100
    cls = "up" if bp >= 0 else "dn"
    return f'<span class="{cls}">{"+" if bp >= 0 else ""}{bp:.0f}bp</span>'


def tag_html(tags):
    out = []
    for t in tags:
        c = "tg"
        if "회복" in t or "신고가" in t:
            c = "tg tg-up"
        elif "이탈" in t or "신저가" in t:
            c = "tg tg-dn"
        elif "테스트" in t:
            c = "tg tg-y"
        out.append(f'<span class="{c}">{t}</span>')
    return " ".join(out)


def fmt_price(v):
    if v != v:
        return "–"
    if v >= 1000:
        return f"{v:,.0f}"
    if v >= 100:
        return f"{v:,.1f}"
    return f"{v:,.2f}"


def arr_cls(a):
    return {"정배열": "a-up", "역배열": "a-dn", "혼조": "a-y"}.get(a, "")


def scan_table(rows_meta, data, compute_fn):
    body = []
    for tk, nm in rows_meta:
        if tk not in data:
            body.append(f'<tr><td class="nm">{nm}</td>'
                        f'<td colspan="6" class="mut">데이터 없음</td></tr>')
            continue
        m = compute_fn(data[tk])
        body.append(
            f'<tr><td class="nm">{nm}</td>'
            f'<td class="r num">{fmt_price(m["close"])}</td>'
            f'<td class="r num">{chg_html(m["chg"])}</td>'
            f'<td class="r num">{gap_html(m["gap"][20])}</td>'
            f'<td class="r num">{gap_html(m["gap"][50])}</td>'
            f'<td class="r num">{gap_html(m["gap"][200])}</td>'
            f'<td class="ar {arr_cls(m["arr"])}">{m["arr"]}</td>'
            f'<td class="tags">{tag_html(m["tags"])}</td></tr>')
    head = ('<tr><th>종목</th><th class="r">종가</th><th class="r">전일</th>'
            '<th class="r">vs20일</th><th class="r">vs50일</th>'
            '<th class="r">vs200일</th><th>배열</th><th>시그널</th></tr>')
    return (f'<div class="table-card"><table class="scan"><thead>{head}</thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def section(key, eyebrow, title, sub, inner):
    return (f'<section id="{key}"><div class="eyebrow"><span class="badge">{eyebrow}</span>'
            f'<span class="sub">{sub}</span></div>'
            f'<h2>{title}</h2>{inner}</section>')


_NAV_LABELS = {
    "narr": "총평", "sources": "소스", "macro": "매크로", "fed": "Fed",
    "us_idx": "미국지수", "global": "글로벌", "semi": "반도체", "sectors": "섹터",
    "rs": "RS랭킹", "m7": "M7·AI", "chart_us": "차트(US)",
    "kr": "한국시장", "chart_kr": "차트(KR)", "aitech": "AI·Tech",
}


def render_nav(keys):
    chips = "".join(f'<a class="nav-chip" href="#{k}">{_NAV_LABELS.get(k, k)}</a>' for k in keys)
    return f'<div class="nav-bar">{chips}</div>'


def chart_grid(charts):
    cells = "".join(
        f'<figure><img src="data:image/png;base64,{b}" alt="{nm}"/></figure>'
        for nm, b in charts)
    return f'<div class="charts">{cells}</div>'


# ══════════════════════════════════════════════════════════════
# 5. 메인 빌드
# ══════════════════════════════════════════════════════════════
def resolve_session(arg):
    if arg in ("us", "kr"):
        return arg
    # 자동: KST 04~16시 = 미국장 마감 직후 → us,  그 외 → kr
    h = datetime.datetime.now(KST).hour
    return "us" if 4 <= h < 16 else "kr"


def _truncate_to_date(data, cutoff):
    """{ticker: df} 딕셔너리의 각 df를 cutoff 날짜까지만 남기고 자른다(과거 시점 재현용)."""
    cutoff_ts = pd.Timestamp(cutoff)
    out = {}
    for k, df in data.items():
        trimmed = df[df.index <= cutoff_ts]
        if len(trimmed) >= 30:
            out[k] = trimmed
    return out


def build(session="auto", theme="coinbase", make_pdf=True, historical_date=None, source_date=None):
    """
    historical_date: datetime.date | 'YYYY-MM-DD' 문자열. 지정하면 그 날짜 마감 기준
    데이터로 과거 시점 리포트를 재현한다(예: 특정 날짜의 버터대디/증시각도기 콘텐츠에
    맞춰 리포트를 다시 만들고 싶을 때). 생략하면 항상 최신 데이터를 사용한다.

    source_date: 원천 콘텐츠(버터대디/증시각도기) 매칭에 쓸 날짜를 직접 지정한다.
    생략하면 기존처럼 ref_date+1(us)/ref_date(kr) 공식으로 자동 계산하는데, 주말
    등으로 거래일 공백이 생기면(예: 금요일 마감 이후 새 거래일 없이 월요일이 되는
    경우) 이 공식이 "오늘"과 어긋날 수 있다. trigger.py는 실행 시점의 실제 오늘
    날짜로 소스 존재 여부를 먼저 확인하므로, 그 날짜를 여기 그대로 넘겨 실제 빌드에
    쓰이는 소스와 트리거 판단에 쓰인 소스가 어긋나지 않게 한다.
    """
    session = resolve_session(session)
    print(f"■ 세션: {'미국 증시 마감' if session=='us' else '한국 증시 마감'} · 테마: {theme}"
          + (f" · 기준일 지정: {historical_date}" if historical_date else ""))

    print("· 미국/글로벌/매크로 수집 (yfinance)…")
    yf_data = fetch_yf(U.YF_ALL)
    print(f"  → {len(yf_data)}/{len(U.YF_ALL)}")
    print("· 한국 지수/종목 수집 (FDR)…")
    kr_idx = fetch_fdr(U.KR_INDICES); kr_stk = fetch_fdr(U.KR_STOCKS)
    print(f"  → 지수 {len(kr_idx)}, 종목 {len(kr_stk)}")

    if historical_date:
        print(f"· {historical_date} 기준으로 데이터 절단…")
        yf_data = _truncate_to_date(yf_data, historical_date)
        kr_idx = _truncate_to_date(kr_idx, historical_date)
        kr_stk = _truncate_to_date(kr_stk, historical_date)
    print("· 예탁금/신용잔고 (네이버)…")
    try:
        money = fetch_kr_money()
    except Exception as e:
        print("  ! 실패:", e); money = None

    print("· 신용잔고 1년 히스토리 + 해석…")
    try:
        money_hist = analytics.fetch_kr_money_history(pages=13)
        credit_interp = analytics.credit_balance_interpretation(money_hist)
    except Exception as e:
        print("  ! 실패:", e); credit_interp = None

    print("· 심화 분석 (시총·시장폭·수급)…")
    mc = analytics.market_cap_analysis()
    breadth = analytics.universe_breadth(
        yf_data, U.US_INDICES + U.SEMI + U.SECTORS + U.M7 + U.GLOBAL + U.AI_CHAIN, compute)
    flows = analytics.stock_investor_flows(U.KR_STOCKS)
    rs = analytics.sector_rs_ranking(yf_data, U.SECTORS + U.SEMI + U.GLOBAL)

    print("· 연준 금리 결정 확률 (Polymarket)…")
    try:
        fed_odds = analytics.fed_rate_odds()
    except Exception as e:
        print("  ! 실패:", e); fed_odds = None

    # 장단기 금리차
    spread = np.nan
    if U.YIELD_LONG in yf_data and U.YIELD_SHORT in yf_data:
        spread = (compute(yf_data[U.YIELD_LONG])["close"]
                  - compute(yf_data[U.YIELD_SHORT])["close"])

    # 기준일 — 세션에 맞는 시장의 마지막 거래일을 사용 (us=미국지수, kr=코스피)
    if session == "kr" and "KS11" in kr_idx:
        ref = kr_idx["KS11"].index[-1]
    elif "^GSPC" in yf_data:
        ref = yf_data["^GSPC"].index[-1]
    else:
        ref = next(iter(yf_data.values())).index[-1] if yf_data else None
    ref_str = ref.strftime("%Y-%m-%d") if ref is not None else "-"
    ref_date = ref.date() if ref is not None else datetime.date.today()
    now_kst = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    # 요약 통계
    n_up = n_dn = arr_g = arr_r = 0; hi_near = []; lo_near = []
    for grp in (U.US_INDICES, U.SEMI, U.SECTORS, U.M7, U.GLOBAL, U.AI_CHAIN):
        for tk, nm in grp:
            if tk in yf_data:
                m = compute(yf_data[tk])
                n_up += m["chg"] >= 0; n_dn += m["chg"] < 0
                arr_g += m["arr"] == "정배열"; arr_r += m["arr"] == "역배열"
                if "신고가 근접" in m["tags"]: hi_near.append(nm)
                if "신저가 근접" in m["tags"]: lo_near.append(nm)
    summary = dict(n_up=int(n_up), n_dn=int(n_dn), arr_g=arr_g, arr_r=arr_r,
                   hi=hi_near, lo=lo_near, spread=spread)

    # 원천 콘텐츠 (버터대디/증시각도기)
    print("· 원천 콘텐츠 확인 (버터대디/증시각도기)…")
    want_date = source_date or srcmod.expected_date(session, ref_date)
    # 거래일 공백(주말·연휴 등으로 want_date가 ref_date+1보다 더 뒤로 밀린 경우,
    # 예: 금요일 마감 다음 월요일 아침) — 시장 데이터는 직전 개장일 것을 그대로
    # 쓰되, 총평 소스는 그 사이(주말 등)에 올라온 글까지 넓혀서 찾는다.
    is_gap = session == "us" and (want_date - ref_date).days > 1
    if is_gap:
        src_start = ref_date + datetime.timedelta(days=1)
        print(f"  (기대 날짜: {want_date.isoformat()} · 거래일 공백 감지, {src_start.isoformat()}~{want_date.isoformat()} 구간에서 탐색)")
        src = srcmod.get_sources_for_range(src_start, want_date, session)
    else:
        print(f"  (기대 날짜: {want_date.isoformat()})")
        src = srcmod.get_sources_for_label_date(want_date, session)
    for k, v in src.items():
        print(f"  - {k}:", v["title"][:40] if v else "없음(미발행)")
    src_list = srcmod.list_recent_sources(session, ref_date, want_date_override=source_date)

    print("· AI-Tech 뉴스 확인…")
    aitech_md, aitech_date = ai_tech.get_ai_tech_markdown(session, datetime.datetime.now(KST).date())
    print("  →", f"{aitech_date.isoformat()} 발행분 확인" if aitech_md else "없음(미발행)")

    # 총평 (원천 콘텐츠 우선, 없으면 웹서치)
    print("· 총평 생성…")
    digest = build_digest(session, yf_data, kr_idx, mc, money, summary, breadth)
    narr = narrative.generate(session, digest, now_kst, sources=src)
    print("  →", "성공" if narr else "생략(규칙 기반 대체)")

    # 차트
    print("· 차트 생성…")
    charts_us = [(nm, chart_b64(yf_data[tk], nm))
                 for tk, nm in U.CHART_TARGETS if tk in yf_data]
    kr_all = {**kr_idx, **kr_stk}
    charts_kr = [(nm, chart_b64(kr_all[tk], nm))
                 for tk, nm in U.CHART_TARGETS_KR if tk in kr_all]

    # 거래일 공백 리포트는 "미국 증시 마감"이 아니라 그날 날짜의 장전 리포트로
    # 제목·아카이브 날짜를 바꾼다(시장 데이터 자체는 ref_str/직전 개장일 그대로).
    gap_info = None
    archive_date_str = ref_str
    report_title = "미국 증시 마감 브리핑" if session == "us" else "한국 증시 마감 브리핑"
    if is_gap:
        weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][want_date.weekday()]
        archive_date_str = want_date.isoformat()
        report_title = f"{want_date.month}월 {want_date.day}일({weekday_kr}) 한국증시 장전 리포트"
        gap_info = dict(display_date=archive_date_str, weekday_kr=weekday_kr, market_ref=ref_str, title=report_title)

    theme_list = ["coinbase", "apple"] if theme == "both" else [theme]
    os.makedirs("out", exist_ok=True)
    outputs = []
    for th in theme_list:
        html = render(session, ref_str, now_kst, yf_data, kr_idx, kr_stk, money,
                      charts_us, charts_kr, summary, mc, breadth, flows, narr, th, rs, src, credit_interp,
                      fed_odds, src_list, aitech_md, aitech_date, gap_info)
        base = f"out/briefing_{session}_{th}_{archive_date_str.replace('-','')}"
        fn = base + ".html"
        with open(fn, "w", encoding="utf-8") as f:
            f.write(html)
        print("· HTML:", fn)
        pdf = None
        if make_pdf:
            try:
                import delivery
                pdf = delivery.html_to_pdf(fn, base + ".pdf")
                print("· PDF :", pdf)
            except Exception as e:
                print("  ! PDF 실패:", repr(e)[:150])
        report_url = viewer_url = None
        try:
            import pages
            report_url, viewer_url = pages.publish_report(session, th, archive_date_str, fn)
            print("· Pages:", viewer_url)
        except Exception as e:
            print("  ! GitHub Pages 발행 실패:", repr(e)[:150])
        outputs.append((th, fn, pdf, report_url, viewer_url))
    return dict(session=session, ref=archive_date_str, market_ref=ref_str, title=report_title,
                narr=narr, summary=summary, mc=mc, outputs=outputs)


def build_digest(session, yf_data, kr_idx, mc, money, summary, breadth):
    """총평용 데이터 요약 텍스트."""
    L = []
    def one(tk):
        return compute(yf_data[tk]) if tk in yf_data else None
    us = []
    for tk, nm in U.US_INDICES + [("SOXX", "반도체")]:
        m = one(tk)
        if m: us.append(f"{nm} {m['chg']:+.2f}%")
    L.append("미국: " + ", ".join(us))
    macro = []
    for tk, nm in U.MACRO:
        m = one(tk)
        if m: macro.append(f"{nm} {fmt_price(m['close'])}")
    L.append("매크로: " + ", ".join(macro[:8]))
    if breadth:
        L.append(f"시장폭: 50일선 상회 {breadth['pct50']:.0f}%, 200일선 상회 {breadth['pct200']:.0f}%")
    kr = []
    for tk, nm in U.KR_INDICES:
        if tk in kr_idx:
            m = compute(kr_idx[tk]); kr.append(f"{nm} {fmt_price(m['close'])}({m['chg']:+.2f}%)")
    L.append("한국: " + ", ".join(kr))
    if "KOSPI" in mc:
        L.append(f"코스피 시총 {mc['KOSPI']['cur']/1e12:,.0f}조(5년내 {mc['KOSPI']['pct5']:.0f}%), "
                 f"버핏지수 {mc.get('buffett', float('nan')):.0f}%")
    if money is not None and len(money):
        r = money.iloc[0]
        L.append(f"고객예탁금 {float(r['고객예탁금'])/10000:.0f}조, 신용융자잔고 {float(r['신용융자잔고'])/10000:.0f}조")
    return "\n".join(L)


# ══════════════════════════════════════════════════════════════
# 6. 렌더 (Coinbase 디자인, 세션 인식)
# ══════════════════════════════════════════════════════════════
def render(session, ref, now, yf_data, kr_idx, kr_stk, money,
           charts_us, charts_kr, summary, mc, breadth, flows, narr, theme="coinbase", rs=None, src=None,
           credit_interp=None, fed_odds=None, src_list=None, aitech_md=None, aitech_date=None, gap_info=None):
    css = themes.get_css(theme, CSS)
    kr_all = {**kr_idx, **kr_stk}
    if gap_info:
        title = gap_info["title"]
        sess_en = "KR Pre-Market"
    else:
        title = "미국 증시 마감 브리핑" if session == "us" else "한국 증시 마감 브리핑"
        sess_en = "US Market Close" if session == "us" else "KR Market Close"

    # ── 예탁금/신용 ──
    def cho(v): return f"{float(v)/10000:.1f}조"
    def cho_chg(v):
        v = float(v) / 10000
        cls, s = ("up", "+") if v >= 0 else ("dn", "")
        return f'<span class="{cls}">{s}{v:.2f}조</span>'
    if money is not None and len(money) >= 1:
        r0 = money.iloc[0]
        yetak, yetak_c = cho(r0["고객예탁금"]), cho_chg(r0["예탁금증감"])
        sinyong, sinyong_c = cho(r0["신용융자잔고"]), cho_chg(r0["신용증감"])
        ratio = float(r0["신용융자잔고"]) / float(r0["고객예탁금"]) * 100
        m_date = r0["날짜"]
    else:
        yetak = yetak_c = sinyong = sinyong_c = "–"; ratio = float("nan"); m_date = "-"
    ratio_s = f"{ratio:.1f}%" if ratio == ratio else "–"

    # ── 총평 섹션 ──
    narr_html = render_narrative(narr, summary, src)
    source_list_html = render_source_list(src_list)

    # ── 매크로 (장단기차 카드 포함) ──
    macro_cards = []
    sp = summary.get("spread", float("nan"))
    if sp == sp:
        sp_cls = "up" if sp >= 0 else "dn"
        macro_cards.append(
            f'<div class="kcard"><div class="kl">장단기 금리차(10Y-3M)</div>'
            f'<div class="kv num {sp_cls}">{sp:+.2f}%p</div>'
            f'<div class="kc mut">{"정상" if sp>=0 else "역전"}</div></div>')
    _YIELD_TICKERS = {"^TNX", "^TYX", "^IRX"}
    for tk, nm in U.MACRO:
        if tk not in yf_data:
            continue
        m = compute(yf_data[tk])
        if tk in _YIELD_TICKERS:
            # 금리는 %변화율만으로는 감이 안 잡히므로 bp 변동을 우선 표시하고 %는 괄호로 병기
            chg_part = f'{bps_html(m["close"], m["prev"])} <span class="mut">({chg_html(m["chg"])})</span>'
        else:
            chg_part = chg_html(m["chg"])
        macro_cards.append(
            f'<div class="kcard"><div class="kl">{nm}</div>'
            f'<div class="kv num">{fmt_price(m["close"])}</div>'
            f'<div class="kc num">{chg_part}</div></div>')
    macro_html = f'<div class="kpi">{"".join(macro_cards)}</div>'

    # ── 시총 수준 섹션 ──
    mcap_html = render_mcap(mc)

    # ── 한국 시장 블록 ──
    ci = credit_interp
    ci_ratio_pct = f"{ci['ratio_pct']:.0f}%" if ci else "–"
    money_block = f'''<div class="money">
      <div class="mcard"><div class="ml">고객예탁금</div><div class="mv num">{yetak}</div><div class="mc num">{yetak_c}</div></div>
      <div class="mcard"><div class="ml">신용융자잔고</div><div class="mv num">{sinyong}</div><div class="mc num">{sinyong_c}</div></div>
      <div class="mcard"><div class="ml">신용 / 예탁금 비율</div><div class="mv num">{ratio_s}</div>
        <div class="mc mut">기준일 {m_date} · 1년내 상위 {ci_ratio_pct if ci else "–"}</div></div>
    </div>'''
    credit_note_html = ""
    if ci:
        credit_note_html = (
            f'<div class="credit-note"><span class="credit-badge">{ci["level_desc"]}</span>'
            f'<p>{ci["sentence"]}</p>'
            f'<div class="credit-gauge"><div class="credit-fill" style="width:{ci["ratio_pct"]:.0f}%"></div>'
            f'<div class="credit-marker" style="left:{ci["ratio_pct"]:.0f}%"></div></div>'
            f'<div class="credit-scale"><span>1년 최저</span><span>1년 최고</span></div>'
            f'<p class="mut" style="font-size:11.5px;margin-top:8px">'
            f'· 신용잔고 자체(금액)의 1년내 위치는 상위 {100-ci["credit_pct"]:.0f}%. '
            f'· 비율이 높을수록 하락 시 반대매매(강제 매도)로 인한 추가 낙폭 위험이 커지고, '
            f'낮을수록 레버리지 청산이 마무리되어 바닥 다지기 국면일 가능성을 시사합니다.</p></div>'
        )
    kr_block = (money_block + credit_note_html + mcap_html
                + scan_table(U.KR_INDICES, kr_all, compute)
                + scan_table(U.KR_STOCKS, kr_all, compute)
                + render_suphgeup(flows))

    # ── 섹션 딕셔너리 ──
    S = {
        "macro":   section("macro", "Macro", "매크로 대시보드", "금리 · 유가 · 환율 · 변동성 · 장단기차", macro_html),
        "fed":     section("fed", "Fed Watch", "연준 금리 결정 확률", "Polymarket 예측시장 실시간 오즈", render_fed_odds(fed_odds)),
        "us_idx":  section("us_idx", "US Index", "미국 4대 지수", "지수 위치 & 이평선 배열", scan_table(U.US_INDICES, yf_data, compute)),
        "global":  section("global", "Global", "글로벌 지수", "유로존 · 신흥국 · 중국 · 한국 · 일본 · 대만", scan_table(U.GLOBAL, yf_data, compute)),
        "semi":    section("semi", "Semiconductor", "반도체", "시장의 중심 섹터", scan_table(U.SEMI, yf_data, compute)),
        "sectors": section("sectors", "Sector Rotation", "섹터 로테이션", "원전 · 전력 · 로봇 · 바이오 · 방산 · 신재생 등", scan_table(U.SECTORS, yf_data, compute)),
        "rs": section("rs", "Relative Strength", "섹터 상대강도(RS) 랭킹", f"S&P500 대비 최근 {rs['lookback']}거래일 초과수익률", render_rs(rs)) if rs else "",
        "m7":      section("m7", "Megacap · AI", "M7 · AI 밸류체인", "빅테크 개별 & 데이터센터 체인", scan_table(U.M7 + U.AI_CHAIN, yf_data, compute)),
        "chart_us": section("chart_us", "Charts · US", "주요 차트 (미국)", "종가 + MA10 / 50 / 200", chart_grid(charts_us)),
        "kr":      section("kr", "KR Market", "한국 시장", "지수 · 시총 수준 · 예탁금 · 신용잔고 · 관심종목", kr_block),
        "chart_kr": section("chart_kr", "Charts · KR", "주요 차트 (한국)", "종가 + MA10 / 50 / 200", chart_grid(charts_kr)),
        "aitech":   render_ai_tech(aitech_md, aitech_date),
    }
    if session == "us":
        order = ["macro", "fed", "us_idx", "global", "semi", "sectors", "rs", "m7", "chart_us", "kr", "chart_kr", "aitech"]
    else:
        order = ["kr", "chart_kr", "macro", "fed", "us_idx", "semi", "sectors", "rs", "m7", "global", "chart_us", "aitech"]
    body_sections = "".join(S[k] for k in order)
    nav_keys = ["narr"] + (["sources"] if source_list_html else []) + [k for k in order if S[k]]
    nav_html = render_nav(nav_keys)

    # ── 히어로 스탯 카드 ──
    b50 = f"{breadth['pct50']:.0f}%" if breadth else "–"
    kospi_pos = f"{mc['KOSPI']['pct5']:.0f}%" if "KOSPI" in mc else "–"
    hero_cards = f'''
      <div class="scard"><div class="sl">스캔 {breadth['n'] if breadth else summary['n_up']+summary['n_dn']}종목 상승 / 하락</div>
        <div class="sv"><span class="up">{summary['n_up']}</span> <span class="sep">/</span> <span class="dn">{summary['n_dn']}</span></div>
        <div class="sc mut">美 지수·반도체·섹터·M7·글로벌 지수</div></div>
      <div class="scard"><div class="sl">시장폭 · 50일선 상회 비율</div>
        <div class="sv num">{b50}</div><div class="sc mut">200일선 상회 {f"{breadth['pct200']:.0f}%" if breadth else "–"}</div></div>
      <div class="scard"><div class="sl">고객예탁금</div>
        <div class="sv num">{yetak}</div><div class="sc num">{yetak_c}</div></div>
      <div class="scard"><div class="sl">코스피 시총 · 5년내 위치</div>
        <div class="sv num">{kospi_pos}</div><div class="sc mut">신용 {sinyong}</div></div>'''

    return f"""<meta charset="utf-8">
<title>{title} · {gap_info['display_date'] if gap_info else ref}</title>
<style>
{css}
</style>

<div class="hero">
  <div class="hero-in">
    <div class="eb">{sess_en}</div>
    <h1>{title}</h1>
    <div class="hsub">{f"시장 데이터는 직전 개장일({gap_info['market_ref']}) 기준 · " if gap_info else ""}생성 {now} · 미국 · 한국 증시 자동 분석</div>
    <div class="stat-cards">{hero_cards}</div>
  </div>
</div>

{nav_html}

<div class="wrap">
  {narr_html}
  {source_list_html}
  {body_sections}
</div>

<footer>
  데이터 · yfinance(미국·글로벌·매크로) / FinanceDataReader(한국 지수·종목·시총) / 네이버 증시자금동향(예탁금·신용잔고) · 총평 · Claude + 웹서치<br>
  이 리포트는 자동 생성된 참고자료이며 투자 권유가 아닙니다. 이평선 · 배열 · 시그널은 규칙 기반 계산, 총평은 AI 생성 결과입니다.<br>
  vs20 / 50 / 200일 = 종가의 해당 이동평균선 대비 이격(%). ▲ 위 · ▼ 아래. · 색상 = 한국 관례(상승 빨강 / 하락 파랑). · 버핏지수는 추정 GDP 기준 참고치.
</footer>
"""


def render_narrative(narr, summary, src=None):
    src = src or {}
    src_badges = "".join(
        f'<a class="src-badge" href="{v["url"]}" target="_blank" rel="noopener">{k} 원문 ↗</a>'
        for k, v in src.items() if v)

    if not narr:
        # 규칙 기반 대체 총평 (원천 콘텐츠 미발행 + 총평 생성도 실패한 경우)
        ov = (f"스캔 종목 기준 상승 {summary['n_up']} / 하락 {summary['n_dn']}, "
              f"정배열 {summary['arr_g']} · 역배열 {summary['arr_r']}. "
              f"신고가 근접: {', '.join(summary['hi']) or '없음'}. "
              f"신저가 근접: {', '.join(summary['lo']) or '없음'}.")
        note = ('버터대디·증시각도기의 오늘자 콘텐츠가 아직 확인되지 않아 데이터 기반 규칙 요약으로 대체했습니다.'
                if not src_badges else '')
        return (f'<section class="brief" id="narr"><div class="eyebrow"><span class="badge badge-key">Briefing</span>'
                f'<span class="sub">규칙 기반 요약</span></div>'
                f'<h2>오늘의 총평</h2><div class="ov-card"><p>{ov}</p>'
                f'{f"<p class=mut style=margin-top:10px;font-size:12.5px>{note}</p>" if note else ""}</div></section>')

    used = narr.get("sources_used") or []
    src_label = " · ".join(used) if used else "웹서치 보강"
    cps = "".join(f'<li>{c}</li>' for c in narr.get("checkpoints", []))
    news = "".join(
        f'<div class="news-row"><div class="news-t">{n.get("title","")}</div>'
        f'<div class="news-i">{n.get("impact","")}</div></div>'
        for n in narr.get("news", []))
    cal = "".join(
        f'<div class="cal-row"><span class="cal-d">{c.get("date","")}</span>'
        f'<span class="cal-e">{c.get("event","")}</span></div>'
        for c in narr.get("calendar", []))
    news_html = news or '<div class="mut" style="font-size:13px">오늘 원천 콘텐츠에 특별히 언급된 뉴스가 없습니다.</div>'
    cal_html = cal or '<div class="mut" style="font-size:13px">오늘 원천 콘텐츠에 언급된 체크 이벤트가 없습니다.</div>'

    # 버터대디/증시각도기 분석을 각각 온전한 별도 카드로 표시(합쳐서 압축하지 않음).
    # 구버전 스키마(overview 단일 필드)로 온 응답도 하위 호환 처리.
    bd_text = narr.get("butterdaddy_analysis")
    jg_text = narr.get("jeungsi_analysis")
    ov_cards = ""
    if bd_text or jg_text:
        if bd_text:
            ov_cards += f'''<div class="ov-card src-card">
              <div class="src-card-h">🧡 버터대디 총평</div>{_paragraphs(bd_text)}</div>'''
        if jg_text:
            ov_cards += f'''<div class="ov-card src-card">
              <div class="src-card-h">📺 증시각도기 총평</div>{_paragraphs(jg_text)}</div>'''
    else:
        ov_cards = f'<div class="ov-card">{_paragraphs(narr.get("overview", ""))}</div>'

    return f'''<section class="brief" id="narr">
      <div class="eyebrow"><span class="badge badge-key">Briefing</span><span class="sub">근거 · {src_label}</span>
      {f'<span class="src-badges">{src_badges}</span>' if src_badges else ''}</div>
      <h2>오늘의 총평</h2>
      <div class="ov-stack">{ov_cards}</div>
      <div class="brief-grid">
        <div class="bcard"><div class="bh">주요 체크포인트</div><ul class="cps">{cps}</ul></div>
        <div class="bcard"><div class="bh">시장 영향 뉴스</div>{news_html}</div>
      </div>
      <div class="bcard cal-card"><div class="bh">체크해야 할 이벤트</div><div class="cal">{cal_html}</div></div>
    </section>'''


def _paragraphs(text):
    """긴 텍스트를 \\n 기준으로 <p> 단락으로 변환(길이 제한 없이 전문 표시).
    마지막 단락은 결론 문단으로 보고 구분선을 넣어 시각적으로 분리한다."""
    if not text:
        return "<p></p>"
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    if not parts:
        return f"<p>{text}</p>"
    html = "".join(f"<p>{p}</p>" for p in parts[:-1])
    html += f'<p class="ov-concl">{parts[-1]}</p>'
    return html


def render_source_list(src_list):
    if not src_list:
        return ""
    rows = ""
    for i, it in enumerate(src_list):
        summary = (it.get("summary") or "").strip()
        lines = [ln.strip() for ln in summary.split("\n") if ln.strip()]
        if not lines:
            rows += f'''<div class="srcl-row">
              <div class="srcl-head">
                <span class="srcl-badge">{it["source"]}</span>
                <span class="srcl-title">{it["title"]}</span>
                <span class="srcl-date mut">{it["date"]}</span>
              </div>
              <p class="srcl-summary mut">요약 준비 중입니다.</p>
              <div class="srcl-actions"><a class="srcl-link" href="{it["url"]}" target="_blank" rel="noopener">원문 보기 ↗</a></div>
            </div>'''
            continue
        preview = lines[0]
        rest = lines[1:]
        rest_html = "".join(f"<p>{ln}</p>" for ln in rest)
        toggle_btn = (f'<button type="button" class="srcl-toggle" onclick="srclToggle(this,{i})">더보기 ▾</button>'
                      if rest else "")
        rows += f'''<div class="srcl-row">
          <div class="srcl-head">
            <span class="srcl-badge">{it["source"]}</span>
            <span class="srcl-title">{it["title"]}</span>
            <span class="srcl-date mut">{it["date"]}</span>
          </div>
          <p class="srcl-summary">{preview}</p>
          <div class="srcl-summary-full" id="srcl-full-{i}" style="display:none">{rest_html}</div>
          <div class="srcl-actions">
            {toggle_btn}
            <a class="srcl-link" href="{it["url"]}" target="_blank" rel="noopener">원문 보기 ↗</a>
          </div>
        </div>'''
    script = '''<script>
    function srclToggle(btn, idx){
      var full = document.getElementById("srcl-full-" + idx);
      var showing = full.style.display !== "none";
      full.style.display = showing ? "none" : "";
      btn.textContent = showing ? "더보기 ▾" : "접기 ▴";
    }
    </script>'''
    return f'''<section class="brief" id="sources">
      <div class="eyebrow"><span class="badge">Sources</span><span class="sub">수집된 원문 글·영상</span></div>
      <h2>주요 블로그 및 영상</h2>
      <div class="srcl-card">{rows}</div>
    </section>{script}'''


def render_ai_tech(md_text, file_date):
    if not md_text:
        return ""
    import markdown as md
    body_html = md.markdown(md_text, extensions=["extra", "sane_lists"])
    date_s = file_date.isoformat() if file_date else ""
    return f'''<section class="brief" id="aitech">
      <div class="eyebrow"><span class="badge">AI · Tech</span><span class="sub">{date_s} 발행</span></div>
      <h2>AI-Tech 뉴스</h2>
      <div class="ov-card aitech-body">{body_html}</div>
    </section>'''


def render_fed_odds(fed_list):
    if not fed_list:
        return '<div class="fed-card mut" style="font-size:13px">Polymarket 데이터를 가져오지 못했습니다.</div>'

    def tab_label(end_date):
        try:
            return f"{end_date[2:4]}.{end_date[5:7]}"
        except Exception:
            return "?"

    tabs, panels = "", ""
    for i, fed in enumerate(fed_list):
        end_date = (fed.get("end_date") or "")[:10]
        active = " fed-tab-active" if i == 0 else ""
        tabs += f'<button type="button" class="fed-tab{active}" onclick="fedShow(this,{i})">{tab_label(fed.get("end_date",""))}</button>'

        top_label = fed["buckets"][0]["label"]
        rows = ""
        for b in fed["buckets"]:
            pct = b["prob"] * 100
            cls = " fed-top" if b["label"] == top_label else ""
            rows += (f'<div class="fed-row{cls}"><div class="fed-label">{b["label"]}</div>'
                     f'<div class="fed-bar"><div class="fed-fill" style="width:{pct:.1f}%"></div></div>'
                     f'<div class="fed-pct num">{pct:.1f}%</div></div>')
        src_url = fed.get("source_url", "")
        disp = "" if i == 0 else "display:none;"
        panels += f'''<div class="fed-panel" id="fed-panel-{i}" style="{disp}">
          <div class="fed-h">{fed.get("title","")} <span class="mut" style="font-weight:400">(회의일 {end_date} 기준)</span></div>
          {rows}
          <div class="mut" style="font-size:11px;margin-top:10px">출처: <a href="{src_url}" target="_blank" rel="noopener">Polymarket 예측시장</a>
          · 실시간 베팅 오즈 기반 확률이며 확정된 결과가 아닙니다.</div>
        </div>'''

    tabs_html = f'<div class="fed-tabs">{tabs}</div>' if len(fed_list) > 1 else ""
    script = '''<script>
    function fedShow(btn, idx){
      var tabs = btn.parentElement.querySelectorAll(".fed-tab");
      tabs.forEach(function(t){ t.classList.remove("fed-tab-active"); });
      btn.classList.add("fed-tab-active");
      document.querySelectorAll(".fed-panel").forEach(function(p){ p.style.display = "none"; });
      document.getElementById("fed-panel-" + idx).style.display = "";
    }
    </script>''' if len(fed_list) > 1 else ""

    return f'<div class="fed-card">{tabs_html}{panels}</div>{script}'


def render_mcap(mc):
    if "KOSPI" not in mc and "KOSDAQ" not in mc:
        return ""
    def card(name, d):
        pct5 = d["pct5"]
        return f'''<div class="mcap-card">
          <div class="mcap-h">{name} 시가총액</div>
          <div class="mcap-v num">{d["cur"]/1e12:,.0f}조</div>
          <div class="mcap-gauge"><div class="mcap-fill" style="width:{pct5:.0f}%"></div></div>
          <div class="mcap-lbl"><span>5년내 위치</span><span class="num">{pct5:.0f}%</span></div>
          <div class="mcap-sub num">1년내 {d["pct1"]:.0f}% · 최고 {d["hi"]/1e12:,.0f}조</div>
        </div>'''
    cards = ""
    if "KOSPI" in mc: cards += card("코스피", mc["KOSPI"])
    if "KOSDAQ" in mc: cards += card("코스닥", mc["KOSDAQ"])
    buf = mc.get("buffett", float("nan"))
    total = mc.get("total", float("nan"))
    if buf == buf:
        lvl = "과열" if buf >= 200 else ("높음" if buf >= 130 else "보통")
        cards += f'''<div class="mcap-card">
          <div class="mcap-h">버핏지수 (시총/GDP)</div>
          <div class="mcap-v num">{buf:.0f}%</div>
          <div class="mcap-gauge"><div class="mcap-fill warn" style="width:{min(buf/2.5,100):.0f}%"></div></div>
          <div class="mcap-lbl"><span>수준</span><span>{lvl}</span></div>
          <div class="mcap-sub num">총시총 {total/1e12:,.0f}조 · 추정 GDP 기준</div>
        </div>'''
    return f'<div class="mcap-grid">{cards}</div>'


def render_rs(rs):
    """섹터 상대강도 랭킹 바 차트(HTML/CSS)."""
    rows = rs["rows"]
    if not rows:
        return '<div class="mut">데이터 없음</div>'
    maxabs = max(abs(r["rs"]) for r in rows) or 1
    bars = []
    for r in rows:
        pct = abs(r["rs"]) / maxabs * 50
        cls = "up" if r["rs"] >= 0 else "dn"
        side = "right" if r["rs"] >= 0 else "left"
        bars.append(
            f'<div class="rs-row"><div class="rs-nm">{r["name"]}</div>'
            f'<div class="rs-track"><div class="rs-mid"></div>'
            f'<div class="rs-bar rs-{side} {cls}" style="width:{pct:.1f}%"></div></div>'
            f'<div class="rs-val num {cls}">{r["rs"]:+.1f}%p</div></div>')
    cap = (f'<div class="mut" style="font-size:12px;margin-bottom:8px">'
           f'기준(S&P500) {rs["bench_ret"]:+.1f}% · 우측(빨강)=시장 대비 강세 · 좌측(파랑)=시장 대비 약세</div>')
    return cap + f'<div class="rs-wrap">{"".join(bars)}</div>'


def render_suphgeup(flows):
    """한국 종목별 수급(외국인·기관 순매매 + 외국인 보유율)."""
    if not flows:
        return ('<div class="subhead" style="font-size:13px;font-weight:600;color:var(--muted);'
                'text-transform:uppercase;letter-spacing:.05em;margin:22px 0 8px;">수급</div>'
                '<div class="mut" style="font-size:13px">수급 데이터를 불러오지 못했습니다.</div>')

    def sh(v):
        if v != v:
            return '<span class="mut">–</span>'
        cls = "up" if v > 0 else "dn"
        return f'<span class="{cls}">{v:+,.0f}</span>'

    rows = []
    for code, _ in U.KR_STOCKS:
        d = flows.get(code)
        if not d:
            continue
        rows.append(
            f'<tr><td class="nm">{d["name"]}</td>'
            f'<td class="r num">{chg_html(d["chgrate"])}</td>'
            f'<td class="r num">{sh(d["forgn"])}</td>'
            f'<td class="r num">{sh(d["inst"])}</td>'
            f'<td class="r num">{d["hold"]:.1f}%</td></tr>')
    head = ('<tr><th>종목</th><th class="r">등락률</th>'
            '<th class="r">외국인 순매매(주)</th><th class="r">기관 순매매(주)</th>'
            '<th class="r">외국인 보유율</th></tr>')
    s = flows.get("_summary", {})
    date = next((v["date"] for k, v in flows.items()
                 if k != "_summary" and isinstance(v, dict)), "-")
    label = ('<div class="subhead" style="font-size:13px;font-weight:600;color:var(--muted);'
             'text-transform:uppercase;letter-spacing:.05em;margin:22px 0 6px;">수급 · 외국인 / 기관 순매매</div>')
    cap = (f'<div class="mut" style="font-size:12.5px;margin:0 2px 10px">'
           f'외국인 순매수 {s.get("forgn_buy",0)}/{s.get("n",0)}종목 · '
           f'기관 순매수 {s.get("inst_buy",0)}/{s.get("n",0)}종목 · 기준일 {date} '
           f'· 순매수 <span class="up">빨강</span> / 순매도 <span class="dn">파랑</span></div>')
    return (label + cap + f'<div class="table-card"><table class="scan"><thead>{head}</thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


# ══════════════════════════════════════════════════════════════
# 7. CSS (Coinbase 기본 테마)
# ══════════════════════════════════════════════════════════════
CSS = """
:root{
  --sans:-apple-system,BlinkMacSystemFont,'Segoe UI','Apple SD Gothic Neo','Malgun Gothic',Roboto,Helvetica,Arial,sans-serif;
  --mono:'SF Mono','JetBrains Mono','Consolas','D2Coding',ui-monospace,monospace;
  --canvas:#fff;--soft:#f7f7f7;--strong:#eef0f3;--card:#fff;
  --ink:#0a0b0d;--body:#5b616e;--muted:#7c828a;--hair:#dee1e6;--hairsoft:#eef0f3;
  --primary:#0052ff;--up:#cf202f;--dn:#0052ff;--warn:#f4b000;
  --hero:#0a0b0d;--herocard:#16181c;--ondark:#fff;--ondarksoft:#a8acb3;--herohair:#26282e;
}
@media (prefers-color-scheme:dark){:root{
  --canvas:#0a0b0d;--soft:#111317;--strong:#16181c;--card:#16181c;
  --ink:#fff;--body:#a8acb3;--muted:#7c828a;--hair:#26282e;--hairsoft:#1c1e23;
  --primary:#4d8dff;--up:#ff5b64;--dn:#4d8dff;--hero:#000;--herocard:#16181c;--herohair:#26282e;
}}
:root[data-theme=dark]{
  --canvas:#0a0b0d;--soft:#111317;--strong:#16181c;--card:#16181c;
  --ink:#fff;--body:#a8acb3;--muted:#7c828a;--hair:#26282e;--hairsoft:#1c1e23;
  --primary:#4d8dff;--up:#ff5b64;--dn:#4d8dff;--hero:#000;--herocard:#16181c;--herohair:#26282e;
}
:root[data-theme=light]{
  --canvas:#fff;--soft:#f7f7f7;--strong:#eef0f3;--card:#fff;
  --ink:#0a0b0d;--body:#5b616e;--muted:#7c828a;--hair:#dee1e6;--hairsoft:#eef0f3;
  --primary:#0052ff;--up:#cf202f;--dn:#0052ff;--hero:#0a0b0d;--herocard:#16181c;--herohair:#26282e;
}
*{box-sizing:border-box;}
body{margin:0;background:var(--canvas);color:var(--ink);font-family:var(--sans);
font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased;}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums;letter-spacing:-.02em;}
.up{color:var(--up);} .dn{color:var(--dn);} .mut{color:var(--muted);} .sep{color:var(--ondarksoft);}

.hero{background:var(--hero);color:var(--ondark);padding:52px 24px 58px;}
.hero-in{max-width:1120px;margin:0 auto;}
.hero .eb{font-size:12px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:var(--ondarksoft);margin-bottom:14px;}
.hero h1{font-size:46px;font-weight:400;letter-spacing:-1.4px;line-height:1.04;margin:0;text-wrap:balance;}
.hero .hsub{color:var(--ondarksoft);font-size:14.5px;margin:12px 0 30px;}
.stat-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;}
.scard{background:var(--herocard);border:1px solid var(--herohair);border-radius:20px;padding:20px 22px;}
.scard .sl{font-size:12.5px;color:var(--ondarksoft);margin-bottom:10px;}
.scard .sv{font-size:26px;font-weight:500;letter-spacing:-.5px;}
.scard .sc{font-size:12.5px;margin-top:5px;}

html{scroll-behavior:smooth;}
.nav-bar{position:sticky;top:0;z-index:30;background:var(--canvas);border-bottom:1px solid var(--hair);
padding:10px 24px;display:flex;gap:8px;overflow-x:auto;white-space:nowrap;-webkit-overflow-scrolling:touch;}
.nav-bar::-webkit-scrollbar{display:none;}
.nav-chip{flex:0 0 auto;font-size:12.5px;font-weight:600;color:var(--body);background:var(--strong);
border-radius:100px;padding:6px 14px;text-decoration:none;}
.nav-chip:hover{color:var(--primary);}

.wrap{max-width:1120px;margin:0 auto;padding:8px 24px 72px;}
section{margin-top:46px;scroll-margin-top:60px;}
.eyebrow{display:flex;align-items:center;gap:12px;margin-bottom:10px;}
.badge{display:inline-block;font-size:11.5px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;
background:var(--strong);color:var(--ink);border-radius:100px;padding:5px 13px;}
.badge-key{background:var(--primary);color:#fff;}
.eyebrow .sub{font-size:13px;color:var(--muted);}
.src-badges{margin-left:auto;display:flex;gap:8px;}
.src-badge{font-size:11.5px;font-weight:600;color:var(--primary);text-decoration:none;
background:var(--strong);border-radius:100px;padding:4px 11px;}
.src-badge:hover{text-decoration:underline;}
.srcl-card{background:var(--card);border:1px solid var(--hair);border-radius:20px;overflow:hidden;}
.srcl-row{padding:18px 20px;border-bottom:1px solid var(--hairsoft);}
.srcl-row:last-child{border-bottom:none;}
.srcl-head{display:flex;align-items:center;gap:12px;flex-wrap:wrap;}
.srcl-badge{flex:0 0 auto;font-size:11px;font-weight:600;color:var(--primary);background:var(--strong);
border-radius:100px;padding:4px 10px;white-space:nowrap;}
.srcl-title{flex:1 1 auto;font-size:13.5px;font-weight:600;color:var(--ink);line-height:1.4;min-width:0;}
.srcl-date{flex:0 0 auto;font-size:12px;font-family:var(--mono);color:var(--muted);white-space:nowrap;}
.srcl-summary{margin:10px 0 0;font-size:13.5px;line-height:1.65;color:var(--body);white-space:pre-line;}
.srcl-summary-full{font-size:13.5px;line-height:1.65;color:var(--body);}
.srcl-summary-full p{margin:8px 0 0;}
.srcl-actions{display:flex;align-items:center;gap:14px;margin-top:10px;}
.srcl-toggle{background:none;border:none;padding:0;font-size:12px;font-weight:600;color:var(--muted);cursor:pointer;}
.srcl-toggle:hover{color:var(--primary);}
.srcl-link{font-size:12px;font-weight:600;color:var(--primary);text-decoration:none;white-space:nowrap;}
.srcl-link:hover{text-decoration:underline;}
h2{font-size:29px;font-weight:400;letter-spacing:-.6px;margin:0 0 16px;color:var(--ink);}

/* 총평 */
.brief{margin-top:34px;}
.ov-stack{display:flex;flex-direction:column;gap:14px;}
.ov-card{background:var(--soft);border-radius:18px;padding:20px 24px;font-size:16px;line-height:1.68;color:var(--ink);}
.ov-card p{margin:0 0 20px;} .ov-card p:last-child{margin-bottom:0;}
.ov-card p.ov-concl{margin-top:4px;padding-top:16px;border-top:1px solid var(--hair);font-weight:600;}
.aitech-body{font-size:15px;}
.aitech-body h1,.aitech-body h2,.aitech-body h3{font-size:15.5px;font-weight:700;color:var(--ink);margin:22px 0 10px;}
.aitech-body h1:first-child,.aitech-body h2:first-child,.aitech-body h3:first-child{margin-top:0;}
.aitech-body p{margin:0 0 16px;}
.aitech-body ul,.aitech-body ol{margin:0 0 16px;padding-left:22px;}
.aitech-body li{margin:6px 0;line-height:1.65;}
.aitech-body li>p{margin:0;}
.aitech-body strong{color:var(--ink);font-weight:700;}
.aitech-body a{color:var(--primary);text-decoration:none;}
.aitech-body a:hover{text-decoration:underline;}
.aitech-body blockquote{margin:0 0 16px;padding:10px 16px;border-left:3px solid var(--primary);
background:var(--strong);border-radius:0 8px 8px 0;color:var(--muted);}
.aitech-body code{background:var(--strong);padding:2px 6px;border-radius:5px;font-family:var(--mono);font-size:.9em;}
.aitech-body pre{background:var(--strong);border-radius:10px;padding:14px 16px;overflow-x:auto;margin:0 0 16px;}
.aitech-body pre code{background:none;padding:0;}
.aitech-body hr{border:none;border-top:1px solid var(--hair);margin:20px 0;}
.src-card{border-left:3px solid var(--primary);}
.src-card-h{font-size:13px;font-weight:700;letter-spacing:.02em;color:var(--primary);margin-bottom:10px;}
.brief-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px;}
.bcard{background:var(--card);border:1px solid var(--hair);border-radius:18px;padding:20px 22px;}
.bh{font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin-bottom:12px;}
ul.cps{margin:0;padding-left:18px;} ul.cps li{margin:7px 0;line-height:1.5;}
.news-row{padding:9px 0;border-bottom:1px solid var(--hairsoft);}
.news-row:last-child{border-bottom:none;}
.news-t{font-weight:600;font-size:14px;line-height:1.4;}
.news-i{font-size:12.5px;color:var(--muted);margin-top:3px;}
.cal-card{margin-top:14px;}
.cal{display:grid;grid-template-columns:repeat(2,1fr);gap:8px 24px;}
.cal-row{display:flex;gap:12px;padding:6px 0;border-bottom:1px solid var(--hairsoft);font-size:13.5px;}
.cal-d{font-family:var(--mono);color:var(--primary);font-weight:600;min-width:112px;white-space:nowrap;}
.cal-e{color:var(--ink);}

.kpi{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}
.kcard{background:var(--card);border:1px solid var(--hair);border-radius:16px;padding:15px 17px;}
.kl{font-size:12px;color:var(--muted);} .kv{font-size:21px;font-weight:500;margin:5px 0 2px;color:var(--ink);} .kc{font-size:13px;}

.mcap-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:16px;}
.mcap-card{background:var(--soft);border-radius:18px;padding:18px 20px;}
.mcap-h{font-size:12.5px;color:var(--muted);}
.mcap-v{font-size:27px;font-weight:600;margin:6px 0 12px;letter-spacing:-.5px;color:var(--ink);}
.mcap-gauge{height:7px;background:var(--strong);border-radius:100px;overflow:hidden;}
.mcap-fill{height:100%;background:var(--primary);border-radius:100px;}
.mcap-fill.warn{background:var(--warn);}
.mcap-lbl{display:flex;justify-content:space-between;font-size:12.5px;margin-top:8px;color:var(--body);}
.mcap-sub{font-size:11.5px;color:var(--muted);margin-top:4px;}

.money{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:16px;}
.mcard{background:var(--soft);border-radius:16px;padding:18px 20px;}
.ml{font-size:12.5px;color:var(--muted);} .mv{font-size:27px;font-weight:500;margin:6px 0 3px;letter-spacing:-.5px;color:var(--ink);} .mc{font-size:13px;}

.credit-note{background:var(--card);border:1px solid var(--hair);border-radius:16px;padding:18px 20px;margin-bottom:16px;}
.credit-badge{display:inline-block;font-size:11.5px;font-weight:600;background:var(--strong);color:var(--ink);
border-radius:100px;padding:4px 12px;margin-bottom:10px;}
.credit-note p{margin:0;font-size:14px;line-height:1.6;color:var(--ink);}
.credit-gauge{position:relative;height:8px;background:var(--strong);border-radius:100px;margin-top:14px;overflow:visible;}
.credit-fill{height:100%;background:var(--primary);border-radius:100px;opacity:.35;}
.credit-marker{position:absolute;top:-3px;width:3px;height:14px;background:var(--primary);border-radius:2px;transform:translateX(-1px);}
.credit-scale{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-top:5px;}

.fed-card{background:var(--card);border:1px solid var(--hair);border-radius:20px;padding:20px 22px;margin-bottom:16px;}
.fed-h{font-size:14px;font-weight:600;color:var(--ink);margin-bottom:14px;}
.fed-row{display:grid;grid-template-columns:120px 1fr 56px;align-items:center;gap:12px;padding:6px 0;}
.fed-label{font-size:13px;color:var(--body);}
.fed-bar{position:relative;height:8px;background:var(--strong);border-radius:100px;overflow:hidden;}
.fed-fill{height:100%;background:var(--muted);border-radius:100px;}
.fed-row.fed-top .fed-fill{background:var(--primary);}
.fed-row.fed-top .fed-label{font-weight:600;color:var(--ink);}
.fed-pct{font-size:13px;text-align:right;color:var(--ink);}
.fed-tabs{display:flex;gap:8px;margin-bottom:16px;}
.fed-tab{background:var(--strong);color:var(--body);border:none;border-radius:100px;padding:7px 16px;font-size:13px;font-weight:600;cursor:pointer;}
.fed-tab-active{background:var(--primary);color:#fff;}

.table-card{background:var(--card);border:1px solid var(--hair);border-radius:20px;overflow-x:auto;margin-bottom:8px;}
table.scan{width:100%;border-collapse:collapse;font-size:13.5px;}
table.scan th{text-align:left;padding:13px 18px;font-weight:600;font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--hair);white-space:nowrap;}
table.scan td{padding:12px 18px;border-bottom:1px solid var(--hairsoft);white-space:nowrap;vertical-align:middle;}
table.scan tbody tr:last-child td{border-bottom:none;}
td.nm{font-weight:600;color:var(--ink);} td.r,th.r{text-align:right;}
td.num .up,td.num .dn{font-weight:500;}
td.ar{font-weight:600;font-size:13px;} .a-up{color:var(--up);} .a-dn{color:var(--dn);} .a-y{color:var(--muted);}
td.tags{white-space:normal;line-height:1.9;}
.tg{display:inline-block;font-size:11px;font-weight:600;padding:3px 10px;border-radius:100px;background:var(--strong);color:var(--muted);margin:1px 3px 1px 0;}
.tg-up{color:var(--up);background:color-mix(in srgb,var(--up) 12%,transparent);}
.tg-dn{color:var(--dn);background:color-mix(in srgb,var(--dn) 12%,transparent);}
.tg-y{color:#9a7500;background:color-mix(in srgb,#f4b000 16%,transparent);}

.charts{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;}
.charts figure{margin:0;background:#fff;border:1px solid var(--hair);border-radius:16px;padding:8px;}
.charts img{width:100%;display:block;border-radius:10px;}

.rs-wrap{background:var(--card);border:1px solid var(--hair);border-radius:20px;padding:18px 22px;}
.rs-row{display:grid;grid-template-columns:110px 1fr 64px;align-items:center;gap:10px;padding:6px 0;}
.rs-nm{font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.rs-track{position:relative;height:16px;background:var(--strong);border-radius:4px;}
.rs-mid{position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--hair);}
.rs-bar{position:absolute;top:1px;bottom:1px;border-radius:3px;}
.rs-bar.rs-right{left:50%;} .rs-bar.rs-left{right:50%;}
.rs-bar.up{background:var(--up);} .rs-bar.dn{background:var(--dn);}
.rs-val{font-size:12px;text-align:right;font-weight:600;}

footer{max-width:1120px;margin:56px auto 0;padding:24px;border-top:1px solid var(--hair);color:var(--muted);font-size:12.5px;line-height:1.7;}

@media(max-width:820px){
  .hero h1{font-size:33px;}
  .stat-cards,.kpi{grid-template-columns:repeat(2,1fr);}
  .brief-grid,.money,.charts,.mcap-grid,.cal{grid-template-columns:1fr;}
}
@media print{
  .wrap{max-width:100%;padding:8px 6px 40px;}
  .hero-in{max-width:100%;}
  .hero{padding:26px 16px;}
  section{margin-top:26px;break-inside:avoid;}
  .table-card,.bcard,.mcap-card,.charts figure,.rs-wrap{break-inside:avoid;}
  table.scan{font-size:11px;}
  table.scan th{padding:7px 8px;font-size:9.5px;}
  table.scan td{padding:6px 8px;white-space:normal;}
  td.nm,td.r{white-space:nowrap;}
  td.tags{white-space:normal;line-height:1.6;}
  .tg{font-size:9.5px;padding:2px 7px;}
  .charts{grid-template-columns:repeat(4,1fr);}
  .kpi{grid-template-columns:repeat(5,1fr);}
}
"""


if __name__ == "__main__":
    # Windows 콘솔 기본 인코딩(cp949)이 이모지/특수문자를 못 받아 무인 실행이 조용히
    # 죽는 것을 방지 — 출력 인코딩을 항상 UTF-8로 고정. (GH Actions Linux 러너는
    # 기본이 UTF-8이라 원래 문제 없음 — 로컬 Windows 실행 안정성을 위한 방어 코드.)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    # 사용: python briefing.py [us|kr|auto] [coinbase|apple]
    session_arg = sys.argv[1] if len(sys.argv) > 1 else "auto"
    theme_arg = sys.argv[2] if len(sys.argv) > 2 else "coinbase"
    build(session_arg, theme_arg)
