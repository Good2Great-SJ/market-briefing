# -*- coding: utf-8 -*-
"""
심화 분석 모듈
  · market_cap_analysis()  : 코스피/코스닥 시가총액 수준(절대치·역사적 위치·버핏지수)
  · universe_breadth()     : 스캔 유니버스 시장폭(이평선 상회 비율)
  · investor_flows()       : 한국 투자자별 순매매(외국인·기관·개인) — best-effort
"""
import warnings, io, datetime
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

# 한국 명목 GDP 추정치(원). 버핏지수(시총/GDP)용 근사값 — 참고 지표.
KR_NOMINAL_GDP = 2600e12


def market_cap_analysis():
    """코스피/코스닥 시총 절대치 + 역사적 위치(percentile) + 버핏지수."""
    import FinanceDataReader as fdr
    out = {}
    total_cur = 0.0
    for code, name in (("KS11", "KOSPI"), ("KQ11", "KOSDAQ")):
        try:
            df = fdr.DataReader(code, "2019-01-01")
            mc = df["MarCap"].dropna().astype(float)
            if len(mc) < 30:
                continue
            cur = mc.iloc[-1]
            total_cur += cur
            out[name] = dict(
                cur=cur,
                pct1=float((mc.tail(252) <= cur).mean() * 100),
                pct5=float((mc <= cur).mean() * 100),
                hi=float(mc.max()),
                lo=float(mc.tail(252 * 5).min()),
                yr_ago=float(mc.tail(252).iloc[0]) if len(mc) >= 252 else np.nan,
                series=mc,
            )
        except Exception:
            pass
    if total_cur:
        out["buffett"] = total_cur / KR_NOMINAL_GDP * 100  # %
        out["total"] = total_cur
    return out


def universe_breadth(data, metas, compute_fn):
    """스캔한 유니버스 기준 시장폭: MA50/MA200 상회 비율, 상승/하락 수."""
    n = above50 = above200 = up = dn = 0
    for tk, _ in metas:
        if tk not in data:
            continue
        m = compute_fn(data[tk])
        n += 1
        if m["gap"][50] == m["gap"][50] and m["gap"][50] >= 0:
            above50 += 1
        if m["gap"][200] == m["gap"][200] and m["gap"][200] >= 0:
            above200 += 1
        up += m["chg"] >= 0
        dn += m["chg"] < 0
    if not n:
        return None
    return dict(n=n, above50=above50, above200=above200,
                pct50=above50 / n * 100, pct200=above200 / n * 100,
                up=int(up), dn=int(dn))


def fetch_kr_money_history(pages=13):
    """
    네이버 증시자금동향(고객예탁금·신용융자잔고) 과거 데이터를 여러 페이지 취합해
    ~1년치(20행×13페이지≈260거래일) 시계열로 반환. 오래된→최신 순 정렬.
    """
    import requests
    h = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"}
    frames = []
    for page in range(1, pages + 1):
        try:
            r = requests.get(f"https://finance.naver.com/sise/sise_deposit.naver?page={page}",
                             headers=h, timeout=15)
            r.encoding = "euc-kr"
            t = pd.read_html(io.StringIO(r.text))[0]
        except Exception:
            break
        cols = ["날짜", "고객예탁금", "예탁금증감", "신용융자잔고", "신용증감",
                "주식형", "주식형증감", "채권형", "채권형증감", "MMF", "MMF증감"]
        t.columns = cols[:len(t.columns)]
        t = t.dropna(subset=["날짜"])
        if len(t) == 0:
            break
        frames.append(t)
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df["날짜"] = pd.to_datetime(df["날짜"], format="%y.%m.%d")
    df = df.sort_values("날짜").drop_duplicates(subset=["날짜"]).reset_index(drop=True)
    return df


def credit_balance_interpretation(history_df):
    """
    신용융자잔고/고객예탁금 데이터를 '해석'으로 변환.
      · 신용잔고·비율의 1년 내 백분위(percentile) — 역사적으로 높은/낮은 수준인지
      · 최근 5거래일 연속 증가/감소 여부(추세) — 디레버리징/레버리징 방향
      · 현재와 가장 비슷한 과거 시점(비율 기준) 검색 — "OO월 수준과 유사"
      · 위 근거로 종합 해석 문장 생성
    """
    if history_df is None or len(history_df) < 20:
        return None
    df = history_df.copy()
    df["ratio"] = df["신용융자잔고"] / df["고객예탁금"] * 100
    cur = df.iloc[-1]
    cur_credit, cur_ratio = float(cur["신용융자잔고"]), float(cur["ratio"])

    credit_pct = float((df["신용융자잔고"] <= cur_credit).mean() * 100)
    ratio_pct = float((df["ratio"] <= cur_ratio).mean() * 100)

    # 최근 5거래일 추세
    last5 = df["신용융자잔고"].tail(6).values
    trend = "증가" if all(x <= y for x, y in zip(last5, last5[1:])) else (
            "감소" if all(x >= y for x, y in zip(last5, last5[1:])) else "혼조")

    # 비율 기준 가장 유사한 과거 시점(현재 제외, 20거래일 이전 데이터 중에서)
    past = df.iloc[:-20] if len(df) > 40 else df.iloc[:-5]
    similar_date, similar_level = None, None
    if len(past) > 0:
        idx = (past["ratio"] - cur_ratio).abs().idxmin()
        similar_date = past.loc[idx, "날짜"].strftime("%Y-%m-%d")
        similar_level = float(past.loc[idx, "ratio"])

    if ratio_pct >= 80:
        level_desc = "1년 내 상위권(과열 근접)"
    elif ratio_pct >= 60:
        level_desc = "평균보다 높은 편"
    elif ratio_pct <= 20:
        level_desc = "1년 내 하위권(디레버리징 진행)"
    elif ratio_pct <= 40:
        level_desc = "평균보다 낮은 편"
    else:
        level_desc = "평균 수준"

    sentence = (
        f"신용/예탁금 비율 {cur_ratio:.1f}%는 최근 1년 분포에서 상위 {100-ratio_pct:.0f}%"
        f"(={level_desc})에 해당합니다. 신용잔고는 최근 5거래일 {trend} 추세이며, "
        + (f"비율만 놓고 보면 {similar_date} 무렵({similar_level:.1f}%)과 비슷한 수준입니다."
           if similar_date else "")
    )

    return dict(
        cur_credit=cur_credit, cur_ratio=cur_ratio,
        credit_pct=credit_pct, ratio_pct=ratio_pct,
        trend=trend, similar_date=similar_date, similar_level=similar_level,
        level_desc=level_desc, sentence=sentence,
        hist_days=len(df),
    )


def sector_rs_ranking(data, sector_metas, bench_ticker="^GSPC", lookback=20):
    """
    섹터 상대강도(RS) 랭킹: 벤치마크(S&P500) 대비 최근 N거래일 초과수익률로 정렬.
    양수=시장 대비 아웃퍼폼, 음수=언더퍼폼.
    """
    if bench_ticker not in data:
        return None
    bench = data[bench_ticker]["Close"].astype(float)
    if len(bench) <= lookback:
        return None
    bench_ret = (bench.iloc[-1] / bench.iloc[-lookback - 1] - 1) * 100
    rows = []
    for tk, nm in sector_metas:
        if tk not in data:
            continue
        c = data[tk]["Close"].astype(float)
        if len(c) <= lookback:
            continue
        ret = (c.iloc[-1] / c.iloc[-lookback - 1] - 1) * 100
        rows.append(dict(name=nm, ret=ret, rs=ret - bench_ret))
    rows.sort(key=lambda r: r["rs"], reverse=True)
    return dict(bench_ret=bench_ret, lookback=lookback, rows=rows)


def _num(v):
    s = str(v).replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except Exception:
        return np.nan


def stock_investor_flows(stocks):
    """
    네이버 종목별 외국인·기관 매매동향(finance.naver.com/item/frgn.naver).
    각 종목 최근 거래일의 등락률 · 기관 순매매(주) · 외국인 순매매(주) · 외국인 보유율.
    → {code: dict}, 그리고 집계 요약.
    """
    import requests
    h = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"}
    out = {}
    for code, name in stocks:
        try:
            r = requests.get(f"https://finance.naver.com/item/frgn.naver?code={code}",
                             headers=h, timeout=12)
            r.encoding = "euc-kr"
            tabs = pd.read_html(io.StringIO(r.text))
            tab = next((t for t in tabs if t.shape[1] == 9 and t.shape[0] > 5), None)
            if tab is None:
                continue
            t2 = tab.dropna(how="all").reset_index(drop=True)
            # 컬럼(위치): 0날짜 1종가 2전일비 3등락률 4거래량 5기관 6외국인 7보유주수 8보유율
            row = None
            for _, rw in t2.iterrows():
                if _num(rw.iloc[6]) == _num(rw.iloc[6]):  # 외국인 값 존재
                    row = rw; break
            if row is None:
                continue
            out[code] = dict(
                name=name, date=str(row.iloc[0]),
                chgrate=_num(row.iloc[3]),
                inst=_num(row.iloc[5]),      # 기관 순매매(주)
                forgn=_num(row.iloc[6]),     # 외국인 순매매(주)
                hold=_num(row.iloc[8]),      # 외국인 보유율(%)
            )
        except Exception:
            pass
    if not out:
        return None
    f_buy = sum(1 for d in out.values() if d["forgn"] > 0)
    i_buy = sum(1 for d in out.values() if d["inst"] > 0)
    out["_summary"] = dict(n=len([k for k in out if k != "_summary"]),
                           forgn_buy=f_buy, inst_buy=i_buy)
    return out


_FED_TITLE_RE = None  # 지연 컴파일(모듈 임포트 시 re 의존 최소화)


def fed_rate_odds(max_meetings=4):
    """
    Polymarket(예측시장)에서 앞으로 예정된 FOMC 회의들의 금리 결정 확률을
    회의일 순으로 모두 가져온다(가장 가까운 회의가 [0]). 인증 불필요(공개
    Gamma API). 실패 시 None(리포트에서 해당 섹션 생략).
    """
    import re, json, requests
    global _FED_TITLE_RE
    if _FED_TITLE_RE is None:
        _FED_TITLE_RE = re.compile(r"^Fed Decision in", re.IGNORECASE)

    try:
        r = requests.get(
            "https://gamma-api.polymarket.com/events",
            params={"tag_slug": "fed", "active": "true", "closed": "false", "limit": 50},
            timeout=10,
        )
        r.raise_for_status()
        events = r.json()
    except Exception:
        return None

    candidates = [e for e in events if _FED_TITLE_RE.match(e.get("title") or "")]
    if not candidates:
        return None
    candidates.sort(key=lambda e: e.get("endDate") or "9999")

    meetings = []
    for ev in candidates[:max_meetings]:
        buckets = []
        for m in ev.get("markets", []):
            try:
                prices = json.loads(m.get("outcomePrices") or "[]")
                yes_prob = float(prices[0])
            except Exception:
                continue
            label = m.get("groupItemTitle") or m.get("question") or ""
            buckets.append(dict(label=label, prob=yes_prob))
        if not buckets:
            continue
        buckets.sort(key=lambda b: -b["prob"])
        meetings.append(dict(
            title=ev.get("title") or "",
            end_date=ev.get("endDate") or "",
            buckets=buckets,
            source="Polymarket",
            source_url=f"https://polymarket.com/event/{ev.get('slug','')}",
        ))
    return meetings or None
