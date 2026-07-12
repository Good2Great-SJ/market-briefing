import json
import os
from datetime import datetime, timedelta

import yaml

from collector.naver_research import classify_stance, collect_new_reports
from consensus.aggregator import build_bootstrap_message, compute_snapshot_summary
from db.db import (
    get_consensus_reports,
    get_consensus_snapshot,
    get_consensus_state,
    has_run_consensus_check_today,
    is_watchlist_stock_bootstrapped,
    mark_consensus_check_ran_today,
    mark_watchlist_stock_bootstrapped,
    upsert_consensus_snapshot,
    upsert_consensus_state,
)
from notifier.kakao_notifier import send_text_message

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")
RESEARCH_LIST_URL = "https://finance.naver.com/research/company_list.naver"

# state.db와 별개의 파일. DB가 (개발 환경의 파일 스냅샷 복원 등 외부 요인으로) 예전 시점으로
# 되돌아가더라도 "이미 어떤 종목에 백필 알림을 보냈는지"는 이 파일로 별도 보존해서,
# DB가 되돌아간 뒤 재실행되었을 때 중복 카톡 발송을 막는다.
CHECKPOINT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "consensus_checkpoint.json")


def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_checkpoint() -> dict:
    if not os.path.exists(CHECKPOINT_PATH):
        return {"notified_bootstrap": {}}
    with open(CHECKPOINT_PATH, encoding="utf-8") as f:
        return json.load(f)


def _mark_checkpoint_notified(stock_code: str, stock_name: str):
    checkpoint = _load_checkpoint()
    checkpoint["notified_bootstrap"][stock_code] = {
        "stock_name": stock_name,
        "notified_at": datetime.now().isoformat(),
    }
    with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)


def _reconcile_watchlist_state_with_checkpoint(logger=print):
    """DB의 consensus_watchlist_state가 체크포인트 파일보다 뒤처져 있으면(=DB가 되돌아간 경우)
    실제로는 이미 알림을 보낸 종목을 다시 '미백필'로 착각해 중복 발송하지 않도록 상태를 복구한다."""
    checkpoint = _load_checkpoint()
    for stock_code, info in checkpoint.get("notified_bootstrap", {}).items():
        if not is_watchlist_stock_bootstrapped(stock_code):
            logger(
                f"[복구] {info['stock_name']}({stock_code})은 {info['notified_at']}에 이미 알림을 보냈으나 "
                f"DB 상태가 되돌아간 것으로 감지됨 — 재발송 없이 상태만 복구합니다."
            )
            mark_watchlist_stock_bootstrapped(stock_code, info["stock_name"])


def _update_state_from_reports(stock_code: str, reports: list[dict]):
    for r in sorted(reports, key=lambda x: x["report_date"]):
        stance = classify_stance(r.get("opinion_raw"))
        upsert_consensus_state(
            stock_code=stock_code,
            broker=r["broker"],
            target_price=r.get("target_price"),
            opinion_raw=r.get("opinion_raw"),
            stance=stance,
            report_date=r["report_date"],
            nid=r["nid"],
        )


def bootstrap_stock(stock_code: str, stock_name: str, lookback_days: int) -> dict:
    """워치리스트 신규 종목의 과거 N일치 리포트를 수집하고, 종합 리포트를 카톡으로 1회 발송한다."""
    since_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    collect_new_reports(stock_code, stock_name, since_date=since_date)

    all_reports = get_consensus_reports(stock_code, since_date=since_date)
    _update_state_from_reports(stock_code, all_reports)

    state = get_consensus_state(stock_code)
    message = build_bootstrap_message(stock_name, stock_code, all_reports, state)
    result = send_text_message(message, f"{RESEARCH_LIST_URL}?itemCode={stock_code}")

    mark_watchlist_stock_bootstrapped(stock_code, stock_name)
    _mark_checkpoint_notified(stock_code, stock_name)
    upsert_consensus_snapshot(stock_code, compute_snapshot_summary(all_reports, state))
    return {"stock_code": stock_code, "stock_name": stock_name, "report_count": len(all_reports), "kakao_result": result}


def send_stock_update(stock_code: str, stock_name: str, lookback_days: int) -> dict:
    """이미 백필된 종목에 신규 리포트가 있으면, 최초 리포트와 동일한 양식으로 전체 컨센서스를
    다시 계산해 그 종목 단독으로 재발송한다 (여러 종목을 묶은 요약이 아니라 종목별 개별 발송).
    직전 발송 시점의 스냅샷과 비교해 이번 신규 리포트로 컨센서스가 상향/하향됐는지도 함께 알려준다."""
    since_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    all_reports = get_consensus_reports(stock_code, since_date=since_date)
    state = get_consensus_state(stock_code)

    previous_snapshot = get_consensus_snapshot(stock_code)
    message = build_bootstrap_message(stock_name, stock_code, all_reports, state, previous_snapshot=previous_snapshot)
    result = send_text_message(message, f"{RESEARCH_LIST_URL}?itemCode={stock_code}")

    upsert_consensus_snapshot(stock_code, compute_snapshot_summary(all_reports, state))
    return {"stock_code": stock_code, "stock_name": stock_name, "report_count": len(all_reports), "kakao_result": result}


def check_watchlist_daily(force: bool = False) -> dict:
    """워치리스트 전 종목의 신규 리포트를 확인한다.

    아직 백필 안 된 종목은 6개월치를 모아 종합 리포트를 1회 발송하고, 이미 백필된 종목은
    신규 리포트가 하나라도 있으면 전체 컨센서스를 재계산해 최초와 동일한 양식으로 그 종목만
    다시 발송한다 (신규 리포트가 없으면 그 종목은 조용히 넘어간다).

    오늘 이미 실행한 적이 있으면 (force=True가 아닌 한) 아무것도 하지 않고 스킵한다 —
    앱을 하루에 여러 번 켜도 중복 실행/중복 알림이 발생하지 않도록 하는 멱등성 가드.
    """
    if not force and has_run_consensus_check_today():
        return {"skipped": True, "reason": "already_ran_today"}

    _reconcile_watchlist_state_with_checkpoint()

    cfg = _load_config()
    watchlist = cfg.get("watchlist_stocks") or []
    consensus_cfg = cfg.get("consensus") or {}
    lookback_days = consensus_cfg.get("lookback_days_bootstrap", 183)

    bootstrapped = []
    updated = []

    for stock in watchlist:
        stock_code = stock["item_code"]
        stock_name = stock["name"]

        if not is_watchlist_stock_bootstrapped(stock_code):
            bootstrapped.append(bootstrap_stock(stock_code, stock_name, lookback_days))
            continue

        daily_since_date = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
        new_reports = collect_new_reports(stock_code, stock_name, since_date=daily_since_date)
        if not new_reports:
            continue

        _update_state_from_reports(stock_code, new_reports)
        updated.append(send_stock_update(stock_code, stock_name, lookback_days))

    mark_consensus_check_ran_today()

    return {
        "skipped": False,
        "bootstrapped": [b["stock_name"] for b in bootstrapped],
        "updated": [u["stock_name"] for u in updated],
    }
