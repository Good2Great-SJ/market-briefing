# -*- coding: utf-8 -*-
"""
자동화 트리거 체커.
  · 미국 증시 마감 체크윈도우 : 싱가폴 07:00 ~ 12:00 (버퍼 후 폴링)
  · 한국 증시 마감 체크윈도우 : 싱가폴 17:00 ~ 23:00 (버퍼 후 폴링)
  각 윈도우 동안 버터대디/증시각도기의 오늘자 콘텐츠가 하나라도 확인되면 즉시
  해당 세션의 briefing.build()를 실행한다. 윈도우 종료(hard stop)까지 아무것도
  안 뜨면 그래도 한 번은 생성한다(원천 없이 규칙/웹서치 기반 총평으로 대체).
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
    "us": (datetime.time(7, 0), datetime.time(12, 0)),
    "kr": (datetime.time(17, 0), datetime.time(23, 0)),
}


def _marker_path(session, date_str):
    return os.path.join(MARKER_DIR, f"{session}_{date_str}.done")


def _already_done(session, date_str):
    return os.path.exists(_marker_path(session, date_str))


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
        if not (start <= t <= hardstop):
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

        reason = "source_ready" if has_source else "hardstop_fallback"
        print(f"[{session}] 트리거 발동 (사유: {reason}) — 브리핑 생성 시작")
        if not dry_run:
            import briefing, delivery
            result = briefing.build(session=session, theme="coinbase", make_pdf=True)
            _mark_done(session, date_str, reason)
            _, fn, pdf = result["outputs"][0]
            fired.append((session, reason, fn))

            if pdf:
                try:
                    label = "미국 증시 마감" if session == "us" else "한국 증시 마감"
                    subject = f"[{label} 브리핑] {result['ref']}"
                    body = delivery.build_email_body(
                        session, result["ref"], result["narr"], result["summary"], result["mc"])
                    delivery.send_email(subject, body, [pdf])
                    print(f"  → 이메일 발송 완료 ({subject})")
                except Exception as e:
                    print("  ! 이메일 발송 실패:", repr(e)[:200])
        else:
            fired.append((session, reason, None))
    return fired


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    fired = check_and_run(dry_run=dry)
    if not fired:
        print("체크 완료 — 트리거된 세션 없음")
    else:
        for session, reason, _ in fired:
            print(f"완료: {session} ({reason})")
