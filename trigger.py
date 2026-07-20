# -*- coding: utf-8 -*-
"""
자동화 트리거 체커.
  · 미국 증시 마감 체크윈도우 : 싱가폴 07:00 ~ 08:00 (하드스톱 08:00)
  · 한국 증시 마감 체크윈도우 : 싱가폴 17:00 ~ 18:00 (하드스톱 18:00)
  각 윈도우 동안 버터대디/증시각도기의 오늘자 콘텐츠가 하나라도 확인되면 즉시
  해당 세션의 briefing.build()를 실행한다. 윈도우 종료(hard stop)까지 아무것도
  안 뜨면 — 그날이 휴장일(주말/공휴일)이 아닌 한 — 원천 없이 규칙 기반 총평으로
  대체해서라도 한 번은 생성한다. 휴장일이면 애초에 소스가 없는 게 정상이므로
  부실한 리포트를 보내지 않고 그냥 건너뛴다.
  하루 세션당 1회만 실행되도록 트리거 마커 파일로 중복 실행을 막는다.

GitHub Actions에서 5~15분 간격 cron으로 이 스크립트만 반복 실행하면 된다.
무거운 작업(briefing.build)은 트리거 조건이 실제로 충족됐을 때만 수행된다.
"""
import os, sys, json, datetime

# Windows 콘솔 기본 인코딩(cp949)이 이모지/특수문자(예: em-dash "—")를 못 받아
# 자동화가 조용히 죽는 것을 방지 — 무인 실행이므로 출력 인코딩을 항상 UTF-8로 고정.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SGT = datetime.timezone(datetime.timedelta(hours=8))
KST = datetime.timezone(datetime.timedelta(hours=9))
MARKER_DIR = os.path.join(os.path.dirname(__file__), "out", ".triggers")

# (세션, 윈도우 시작 SGT 시각, 하드스톱 SGT 시각)
WINDOWS = {
    "us": (datetime.time(7, 0), datetime.time(8, 0)),
    "kr": (datetime.time(17, 0), datetime.time(18, 0)),
}


def _marker_path(session, date_str):
    return os.path.join(MARKER_DIR, f"{session}_{date_str}.done")


def _already_done(session, date_str):
    if os.path.exists(_marker_path(session, date_str)):
        return True
    # out/ 마커 파일은 워크플로우 자신이 매 실행 뒤 커밋해야 다음 실행에 남는데,
    # (예: 로컬에서 소스만 수동으로 push하고 out/는 안 올린 경우) 그 커밋이 누락되면
    # 마커가 유실돼 이미 발행된 세션을 또 재발행·재발송할 수 있다. docs/manifest.json은
    # 항상 함께 커밋되는 실제 발행 기록이므로 이걸로도 한 번 더 확인한다.
    try:
        manifest_path = os.path.join(os.path.dirname(__file__), "docs", "manifest.json")
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        return any(r.get("session") == session and r.get("date") == date_str for r in manifest)
    except Exception:
        return False


def _mark_done(session, date_str, reason):
    os.makedirs(MARKER_DIR, exist_ok=True)
    with open(_marker_path(session, date_str), "w", encoding="utf-8") as f:
        json.dump({"reason": reason, "at": datetime.datetime.now(SGT).isoformat()}, f, ensure_ascii=False)


def check_and_run(now_sgt=None, dry_run=False):
    now_sgt = now_sgt or datetime.datetime.now(SGT)
    date_str = now_sgt.date().isoformat()
    t = now_sgt.time()

    fired = []
    for session, (start, hardstop) in WINDOWS.items():
        # start 이후라면 하드스톱을 넘겼어도 계속 체크한다(상한을 두지 않음).
        # GitHub Actions cron은 실행 시각이 몇 분 밀리거나 아예 한 번 건너뛸 수
        # 있는데, 하드스톱 시각을 상한으로 삼아 "그 순간 지나면 오늘은 포기"
        # 하도록 짜여 있으면 그 한 번의 지연만으로 하루치 리포트가 통째로
        # 누락된다. 이미 발행됐는지는 마커 파일로 걸러지므로 상한이 없어도
        # 중복 발행 위험은 없다.
        if t < start:
            continue
        if _already_done(session, date_str):
            continue

        import sources
        # 체크윈도우 시각대에는 "오늘의 KST 캘린더 날짜"가 곧 두 세션 모두의 기대 날짜와 같다.
        # (us: 미국장 마감일+1일=오늘, kr: 한국장 마감일=오늘)
        today_kst = now_sgt.astimezone(KST).date()
        src = sources.get_sources_for_label_date(today_kst, session)
        has_source = sources.has_any(src)
        is_hardstop = t >= hardstop

        if not (has_source or is_hardstop):
            print(f"[{session}] 대기 중 — 원천 콘텐츠 아직 없음 (윈도우 {start}~{hardstop}, 현재 {t})")
            continue

        if not has_source and is_hardstop:
            import calendars
            market_date = today_kst if session == "kr" else today_kst - datetime.timedelta(days=1)
            is_holiday = (calendars.is_kr_market_holiday(market_date) if session == "kr"
                          else calendars.is_us_market_holiday(market_date))
            if is_holiday:
                print(f"[{session}] 건너뜀 — {market_date} 휴장일(주말/공휴일)이라 소스도 없음, 발송 생략")
                if not dry_run:
                    _mark_done(session, date_str, "holiday_skip")
                continue

        reason = "source_ready" if has_source else "hardstop_fallback"
        print(f"[{session}] 트리거 발동 (사유: {reason}) — 브리핑 생성 시작")
        if not dry_run:
            import briefing
            # source_date=today_kst: 위에서 이미 today_kst 기준으로 소스 존재를
            # 확인해 트리거를 발동시켰으므로, 실제 빌드도 같은 날짜로 소스를 찾게
            # 한다. 주말 등 거래일 공백 직후(예: 월요일)에는 시장 데이터 기준일
            # (ref_date)만으로 역산한 '기대 날짜'가 오늘과 어긋나 다른 소스를
            # 찾아버리는 문제가 있었다 — 시장 데이터는 직전 영업일 것을 그대로
            # 쓰되, 총평/블로그·영상/AI-Tech는 항상 오늘 날짜 기준 최신으로 맞춘다.
            result = briefing.build(session=session, theme="coinbase", make_pdf=False,
                                     source_date=today_kst)
            _mark_done(session, date_str, reason)
            _, fn, pdf, report_url, viewer_url = result["outputs"][0]
            fired.append((session, reason, fn))
            _send_report_email(session, result, viewer_url)
        else:
            fired.append((session, reason, None))
    return fired


def _send_report_email(session, result, viewer_url, note=None):
    """리포트가 새로 생성/재발행될 때마다 이메일도 함께 보낸다.

    note가 있으면(자막 지연 재발행 등) 제목에 덧붙여 일반 발행과 구분한다.
    """
    import delivery
    try:
        subject = f"[{result['title']}] {result['ref']}" + (f" ({note})" if note else "")
        body = delivery.build_email_body(
            session, result["ref"], result["narr"], result["summary"], result["mc"],
            link_url=viewer_url or "")
        delivery.send_email(subject, body, [])
        print(f"  → 이메일 발송 완료 ({subject})")
    except Exception as e:
        print("  ! 이메일 발송 실패:", repr(e)[:200])


PENDING_RETRY_HOURS = 6  # naver-blog-kakao-notifier의 TRANSCRIPT_RETRY_HOURS(자막 재시도 포기 시한)과 맞춤


def recheck_pending_updates(now_sgt=None):
    """자막이 늦게 붙는 원천(주로 증시각도기 라이브 방송)을 감지해 리포트를 재발행한다.

    briefing.build()는 매칭된 원천 중 status=transcript_pending인 게 있으면
    out/.triggers/{session}_{date}.pending.json에 마커를 남긴다. 여기서 그
    마커들을 훑어 자막이 실제로 붙었는지(status가 collected 등으로 바뀌었는지)
    확인하고, 붙었으면 같은 날짜로 브리핑을 재빌드해 같은 파일명/아카이브
    항목을 덮어쓴다(새 아카이브 항목이 늘어나지 않음). PENDING_RETRY_HOURS가
    지나도 안 붙으면 — naver-blog-kakao-notifier 쪽도 그때는 포기하므로 —
    마커를 지우고 더는 확인하지 않는다.
    """
    now_sgt = now_sgt or datetime.datetime.now(SGT)
    updated = []
    if not os.path.isdir(MARKER_DIR):
        return updated

    import sources, briefing
    for fn in sorted(os.listdir(MARKER_DIR)):
        if not fn.endswith(".pending.json"):
            continue
        path = os.path.join(MARKER_DIR, fn)
        try:
            with open(path, encoding="utf-8") as f:
                marker = json.load(f)
        except Exception:
            continue

        # status가 바뀌어도(naver-blog-kakao-notifier가 재시도를 포기해도) 자막
        # 없이 설명란만으로 확정된 경우엔 내용이 그대로라 다시 빌드해봐야 무의미
        # 하다 — 실제로 분량이 늘어난 경우만 "해결됨"으로 본다.
        still_pending, resolved = {}, False
        for pid, baseline_len in marker["pending"].items():
            post = sources.get_post_by_id(pid)
            rclen = len(post.get("raw_content") or "") if post else baseline_len
            if post and post.get("status") != "transcript_pending" and rclen > baseline_len + 100:
                resolved = True
            else:
                still_pending[pid] = baseline_len

        if resolved:
            print(f"[재발행] {marker['session']} {marker['archive_date']} — 지연 자막 입수, 리포트 갱신")
            src_date = datetime.date.fromisoformat(marker["source_date"])
            result = briefing.build(session=marker["session"], theme=marker.get("theme", "coinbase"),
                                     make_pdf=False, source_date=src_date)
            _, _, _, _, viewer_url = result["outputs"][0]
            _send_report_email(marker["session"], result, viewer_url, note="자막 반영 갱신")
            updated.append((marker["session"], marker["archive_date"]))

        elapsed_h = (now_sgt - datetime.datetime.fromisoformat(marker["first_seen"])).total_seconds() / 3600
        if still_pending and elapsed_h < PENDING_RETRY_HOURS:
            marker["pending"] = still_pending
            with open(path, "w", encoding="utf-8") as f:
                json.dump(marker, f, ensure_ascii=False)
        else:
            os.remove(path)
    return updated


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    fired = check_and_run(dry_run=dry)
    if not fired:
        print("체크 완료 — 트리거된 세션 없음")
    else:
        for session, reason, _ in fired:
            print(f"완료: {session} ({reason})")
    if not dry:
        updated = recheck_pending_updates()
        for session, date_str in updated:
            print(f"재발행 완료: {session} ({date_str})")
