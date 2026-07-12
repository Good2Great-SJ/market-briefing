from collections import defaultdict
from datetime import datetime

RESEARCH_LIST_URL = "https://finance.naver.com/research/company_list.naver"


def _valid_reports_with_price(reports: list[dict]) -> list[dict]:
    return [r for r in reports if r.get("target_price")]


def compute_target_price_consensus(reports: list[dict], state: dict[str, dict]) -> dict:
    """브로커별 최신 상태(state) 기준 목표가 평균/범위와, 수집 기간 첫 달 평균 대비 변화율을 계산한다."""
    latest_prices = [s["target_price"] for s in state.values() if s.get("target_price")]

    baseline_avg = None
    if reports:
        first_month = reports[0]["report_date"][:7]
        first_month_prices = [
            r["target_price"] for r in reports if r["report_date"][:7] == first_month and r.get("target_price")
        ]
        if first_month_prices:
            baseline_avg = sum(first_month_prices) / len(first_month_prices)

    latest_avg = sum(latest_prices) / len(latest_prices) if latest_prices else None
    change_pct = None
    if baseline_avg and latest_avg:
        change_pct = (latest_avg - baseline_avg) / baseline_avg * 100

    return {
        "latest_avg": latest_avg,
        "baseline_avg": baseline_avg,
        "change_pct": change_pct,
        "min": min(latest_prices) if latest_prices else None,
        "max": max(latest_prices) if latest_prices else None,
        "broker_count": len(latest_prices),
    }


def compute_stance_distribution(state: dict[str, dict]) -> dict:
    dist = {"낙관": 0, "중립": 0, "비관": 0}
    for s in state.values():
        stance = s.get("stance") or "중립"
        dist[stance] = dist.get(stance, 0) + 1
    return dist


def compute_margin_trend(reports: list[dict], year_kind: str = "current") -> list[tuple[str, float]]:
    """월별 영업이익률(영업이익/매출액) 평균 추이를 계산한다. [(month, avg_margin), ...]

    year_kind='current': 당해년도 추정치 기준 — 이미 발표된 분기 실적이 섞여 들어가 실적 서프라이즈에
    따른 눈높이 변화를 반영한다.
    year_kind='next': 차년도(내년) 추정치 기준 — 실제 발표된 실적의 직접 영향이 적어 펀더멘털 전망
    자체의 변화에 가깝다.
    """
    revenue_key = f"revenue_estimate_{year_kind}"
    op_profit_key = f"operating_profit_estimate_{year_kind}"

    monthly = defaultdict(list)
    for r in reports:
        revenue = r.get(revenue_key)
        op_profit = r.get(op_profit_key)
        if not revenue or not op_profit:
            continue
        month = r["report_date"][:7]
        monthly[month].append(op_profit / revenue * 100)

    return [(month, sum(vals) / len(vals)) for month, vals in sorted(monthly.items())]


def get_recent_comments(reports: list[dict], n: int = 3) -> list[dict]:
    return sorted(reports, key=lambda r: r["report_date"], reverse=True)[:n]


def _format_price(price: int | float | None) -> str:
    if not price:
        return "-"
    return f"{price / 10000:.1f}만원"


def compute_snapshot_summary(reports: list[dict], state: dict[str, dict]) -> dict:
    """이번 계산 시점의 컨센서스를 몇 개 숫자로 압축한다 — 다음 업데이트 때 이 값과 비교해
    상향/하향을 판단하는 기준값으로 쓰인다."""
    price_info = compute_target_price_consensus(reports, state)
    stance_dist = compute_stance_distribution(state)
    trend_current = compute_margin_trend(reports, year_kind="current")
    trend_next = compute_margin_trend(reports, year_kind="next")
    return {
        "avg_target_price": price_info["latest_avg"],
        "margin_current": trend_current[-1][1] if trend_current else None,
        "margin_next": trend_next[-1][1] if trend_next else None,
        "optimistic": stance_dist["낙관"],
        "neutral": stance_dist["중립"],
        "pessimistic": stance_dist["비관"],
    }


def _build_delta_line(previous: dict | None, current: dict) -> str:
    """직전 스냅샷 대비 이번 업데이트로 컨센서스가 상향/하향됐는지 짧게 요약한다."""
    if not previous:
        return ""

    parts = []
    direction = 0

    prev_price = previous.get("avg_target_price")
    cur_price = current.get("avg_target_price")
    if prev_price and cur_price and prev_price != cur_price:
        pct = (cur_price - prev_price) / prev_price * 100
        if abs(pct) >= 0.1:
            parts.append(f"목표가 {_format_price(prev_price)}→{_format_price(cur_price)}({pct:+.1f}%)")
            direction += 1 if pct > 0 else -1

    prev_margin = previous.get("margin_current")
    cur_margin = current.get("margin_current")
    if prev_margin is not None and cur_margin is not None and abs(cur_margin - prev_margin) >= 0.1:
        parts.append(f"당해년도 영업이익률 {prev_margin:.1f}%→{cur_margin:.1f}%p")
        direction += 1 if cur_margin > prev_margin else -1

    prev_score = (previous.get("optimistic") or 0) - (previous.get("pessimistic") or 0)
    cur_score = (current.get("optimistic") or 0) - (current.get("pessimistic") or 0)
    if prev_score != cur_score:
        parts.append(f"낙관우위 {prev_score:+d}→{cur_score:+d}")
        direction += 1 if cur_score > prev_score else -1

    if not parts:
        return "📌 이번 업데이트 효과: 컨센서스 변화 미미 (보합)"

    label = "컨센서스 상향" if direction > 0 else ("컨센서스 하향" if direction < 0 else "혼조 (상향·하향 신호 혼재)")
    return f"📌 이번 업데이트 효과: {', '.join(parts)} → {label}"


def build_bootstrap_message(
    stock_name: str,
    stock_code: str,
    reports: list[dict],
    state: dict[str, dict],
    previous_snapshot: dict | None = None,
) -> str:
    """종합 컨센서스 리포트 메시지. previous_snapshot이 주어지면(=신규 리포트로 인한 업데이트 발송)
    직전 스냅샷 대비 상향/하향 여부를 알려주는 델타 라인이 추가된다."""
    price_info = compute_target_price_consensus(reports, state)
    stance_dist = compute_stance_distribution(state)
    margin_trend_current = compute_margin_trend(reports, year_kind="current")
    margin_trend_next = compute_margin_trend(reports, year_kind="next")
    recent = get_recent_comments(reports, n=3)

    period = f"{reports[0]['report_date'][:7].replace('-', '.')}~{reports[-1]['report_date'][:7].replace('-', '.')}" if reports else ""

    if price_info["change_pct"] is not None:
        one_liner = (
            f"목표가 {price_info['change_pct']:+.0f}%, "
            f"{'낙관' if stance_dist['낙관'] >= stance_dist['비관'] else '비관'} 우세"
        )
    else:
        one_liner = "데이터 수집 완료"

    price_line = (
        f"{_format_price(price_info['baseline_avg'])} → {_format_price(price_info['latest_avg'])}"
        f"  ({price_info['change_pct']:+.0f}%, {period})"
        if price_info["change_pct"] is not None
        else f"{_format_price(price_info['latest_avg'])} (브로커 {price_info['broker_count']}곳)"
    )

    def _trend_summary(trend: list[tuple[str, float]]) -> str:
        if len(trend) < 2:
            return ""
        first_m, first_v = trend[0]
        last_m, last_v = trend[-1]
        return f"{first_m[5:]}월 {first_v:.1f}% → {last_m[5:]}월 {last_v:.1f}%"

    current_year = datetime.now().year
    margin_lines = []
    current_summary = _trend_summary(margin_trend_current)
    next_summary = _trend_summary(margin_trend_next)
    if current_summary:
        margin_lines.append(f"{current_year}F(실적반영): {current_summary}")
    if next_summary:
        margin_lines.append(f"{current_year + 1}F(펀더멘털 전망): {next_summary}")

    margin_line = f"\n\n📈 영업이익률 추이\n" + "\n".join(margin_lines) if margin_lines else ""

    comment_lines = []
    for r in recent:
        stance_tag = f"{r['broker']} {r.get('opinion_raw') or '-'}·{_format_price(r.get('target_price'))}"
        comment_lines.append(f"• {stance_tag} \"{r['title']}\"")
    comments_block = "\n".join(comment_lines)

    delta_text = _build_delta_line(previous_snapshot, compute_snapshot_summary(reports, state))
    delta_block = f"\n\n{delta_text}" if delta_text else ""

    return f"""\
📊 [{stock_name}] 컨센서스 리포트 ({period}){delta_block}

한줄요약: {one_liner}

💰 목표가 컨센서스
{price_line}
브로커 {price_info['broker_count']}곳 (최저 {_format_price(price_info['min'])} ~ 최고 {_format_price(price_info['max'])})

🎯 투자의견 분포
낙관 {stance_dist['낙관']} · 중립 {stance_dist['중립']} · 비관 {stance_dist['비관']}{margin_line}

📝 최근 코멘트
{comments_block}

🔗 리포트 전체보기: {RESEARCH_LIST_URL}?itemCode={stock_code}"""
