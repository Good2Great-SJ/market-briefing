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
    # (예: 로컬에서 소스만 수동으로 push하고 out/는 안 올린 경우, 또는 병합 충돌
    # 해결 중 실수로 지워버린 경우 — 2026-07-25 us 세션 실사고) 그 커밋이 누락되면
    # 마커가 유실돼 이미 발행된 세션을 또 재발행·재발송할 수 있다. docs/manifest.json은
    # 항상 함께 커밋되는 실제 발행 기록이므로 이걸로도 한 번 더 확인한다.
    #
    # 주의 1: manifest 항목의 "date"는 리포트의 ref_date(예: us 세션은 보통 전날)이지
    # "오늘"이 아니다 — r["date"] == date_str로만 비교하면 us 세션에서는 거의 항상
    # 어긋나 이 안전장치가 사실상 무력화된다(2026-07-25 us 실사고 원인). us는
    # ref_date가 today-1인 경우가 흔하므로 그 후보도 함께 확인한다.
    #
    # 주의 2: generated_at은 자막 지연 등으로 조용히 재발행(recheck_pending_updates)될
    # 때마다 갱신되는 "마지막 손댄 시각"이라, 자정을 넘겨 갱신되면 그 날짜가 우연히
    # 오늘 date_str과 같아져 어제 리포트를 "오늘 이미 발행됨"으로 오판할 수 있다
    # (2026-07-28 kr 세션 실사고 — 어젯밤 01:52에 조용히 갱신된 것 때문에 오늘 하루
    # 종일 발행이 막혔음). 그래서 generated_at이 아니라 안정적인 date 필드로만 비교한다.
    try:
        manifest_path = os.path.join(os.path.dirname(__file__), "docs", "manifest.json")
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        candidates = {date_str}
        if session == "us":
            d = datetime.date.fromisoformat(date_str) - datetime.timedelta(days=1)
            candidates.add(d.isoformat())
        return any(r.get("session") == session and (r.get("date") or "")[:10] in candidates
                   for r in manifest)
    except Exception:
        return False


def _mark_done(session, date_str, reason):
    os.makedirs(MARKER_DIR, exist_ok=True)
    with open(_marker_path(session, date_str), "w", encoding="utf-8") as f:
        json.dump({"reason": reason, "at": datetime.datetime.now(SGT).isoformat()}, f, ensure_ascii=False)


def _email_marker_path(session, date_str):
    return os.path.join(MARKER_DIR, f"{session}_{date_str}.email_sent")


def _email_already_sent(session, date_str):
    return os.path.exists(_email_marker_path(session, date_str))


def _already_published_upstream(session, date_str):
    """이메일 발송 직전, 원격 최신 상태로 한 번 더 "이미 발행됐는지" 확인한다.

    GitHub 자체 schedule과 cron-job.org의 독립적인 workflow_dispatch가 거의
    동시에(수십~수백 초 간격) 실행되면, 둘 다 이 로컬 체크아웃 시점 기준으로는
    "아직 발행 안 됨"을 보고 각자 빌드·발송을 진행해버릴 수 있다(concurrency 잠금이
    이 정도로 촘촘한 경합까지는 못 막았던 2026-08-06 KR 세션 중복 발송 실사고).
    로컬 체크아웃은 이 작업 시작 시점의 스냅샷이라 그 사이 다른 실행이 먼저
    커밋·푸시했어도 반영되지 않으므로, 발송 직전에 origin의 최신 manifest.json을
    직접 확인해 이미 발행됐으면 중복 이메일을 보내지 않는다. 이 확인 자체가
    실패해도(네트워크 등) 기존 동작을 막지 않도록 조용히 무시하고 진행한다."""
    import subprocess
    try:
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        subprocess.run(["git", "fetch", "origin", "main", "-q"],
                        cwd=repo_dir, timeout=30, check=True)
        proc = subprocess.run(["git", "show", "origin/main:docs/manifest.json"],
                               cwd=repo_dir, timeout=30, check=True,
                               capture_output=True, text=True)
        manifest = json.loads(proc.stdout)
        candidates = {date_str}
        if session == "us":
            d = datetime.date.fromisoformat(date_str) - datetime.timedelta(days=1)
            candidates.add(d.isoformat())
        return any(r.get("session") == session and (r.get("date") or "")[:10] in candidates
                   for r in manifest)
    except Exception as e:
        print(f"  ! 원격 재확인 실패(무시하고 진행): {repr(e)[:200]}")
        return False


def _mark_email_sent(session, date_str):
    os.makedirs(MARKER_DIR, exist_ok=True)
    with open(_email_marker_path(session, date_str), "w", encoding="utf-8") as f:
        json.dump({"at": datetime.datetime.now(SGT).isoformat()}, f, ensure_ascii=False)


def _email_payload_path(session, date_str):
    return os.path.join(MARKER_DIR, f"{session}_{date_str}.email.json")


# 발송 실패 시 워크플로우 잡을 눈에 띄게 실패 처리하기 위한 플래그 파일.
# (기존엔 발송 실패도 로그 한 줄로 삼켜져 잡이 초록색 성공으로 표시됐고,
#  아무도 눈치채지 못한 채 이메일이 누락됐다 — 2026-07-21~22 실사고 3건.)
EMAIL_FAILED_FLAG = os.path.join(MARKER_DIR, "EMAIL_FAILED")

# 발송 재시도 유효 시간. 이보다 오래된 미발송 페이로드는 내용이 낡아
# 보내는 의미가 없으므로 폐기한다(다음 세션 리포트가 곧 나올 시간).
EMAIL_RETRY_HOURS = 12


def _save_email_payload(session, date_str, subject, body, html_body):
    """발송할 이메일 내용을 디스크에 보관한다.

    발송이 실패해도 다음 15분 주기 실행이 이 파일을 읽어 재시도할 수 있도록
    — 리포트 재빌드 없이 — 발송에 필요한 전부를 저장해 둔다. 이 파일은
    워크플로우가 out/과 함께 커밋하므로 실행(러너)이 바뀌어도 유지된다."""
    os.makedirs(MARKER_DIR, exist_ok=True)
    with open(_email_payload_path(session, date_str), "w", encoding="utf-8") as f:
        json.dump({"subject": subject, "body": body, "html_body": html_body,
                   "created_at": datetime.datetime.now(SGT).isoformat()}, f, ensure_ascii=False)


def retry_unsent_emails(now_sgt=None):
    """발행은 됐는데 이메일 발송이 안 된 리포트를 찾아 재발송한다.

    저장된 페이로드(*.email.json) 중 .email_sent 마커가 없는 것이 대상.
    성공하면 마커를 남기고 페이로드를 지운다. EMAIL_RETRY_HOURS를 넘긴
    페이로드는 낡은 내용이므로 재발송 없이 폐기한다."""
    now_sgt = now_sgt or datetime.datetime.now(SGT)
    if not os.path.isdir(MARKER_DIR):
        return
    import delivery
    any_failed = False
    for fn in sorted(os.listdir(MARKER_DIR)):
        if not fn.endswith(".email.json"):
            continue
        key = fn[:-len(".email.json")]          # "{session}_{date_str}"
        session, _, date_str = key.partition("_")
        path = os.path.join(MARKER_DIR, fn)
        if _email_already_sent(session, date_str):
            os.remove(path)                      # 이미 발송됨 — 페이로드 정리만
            continue
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            os.remove(path)
            continue
        age_h = (now_sgt - datetime.datetime.fromisoformat(payload["created_at"])).total_seconds() / 3600
        if age_h > EMAIL_RETRY_HOURS:
            print(f"[이메일 재시도] {key} — {age_h:.1f}시간 경과, 내용이 낡아 폐기")
            os.remove(path)
            continue
        print(f"[이메일 재시도] {key} — 이전 실행에서 발송 실패분 재발송 시도")
        try:
            delivery.send_email(payload["subject"], payload["body"], [],
                                html_body=payload.get("html_body"))
            print(f"  → 재발송 성공 ({payload['subject']})")
            _mark_email_sent(session, date_str)
            os.remove(path)
        except Exception as e:
            print("  ! 재발송도 실패:", repr(e)[:200])
            any_failed = True
    if any_failed:
        with open(EMAIL_FAILED_FLAG, "w", encoding="utf-8") as f:
            f.write(datetime.datetime.now(SGT).isoformat())
    elif os.path.exists(EMAIL_FAILED_FLAG):
        os.remove(EMAIL_FAILED_FLAG)


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
            # 콘텐츠는 이미 발행됐지만(마커 파일 또는 manifest.json 기준) 이 실행이
            # 그걸 직접 만든 게 아닐 수 있다 — 예: 디버깅 중 수동으로 briefing.build()를
            # 돌려 site만 갱신한 경우, 정식 자동화 흐름(이 함수)이 한 번도 실행되지
            # 않아 이메일이 영영 발송되지 않는 사고가 있었다(2026-07-21 KR 리포트 실사고).
            # 재발 방지를 위해 최소한 눈에 띄는 경고라도 남긴다.
            if not _email_already_sent(session, date_str):
                print(f"[{session}] ! 경고 — {date_str} 리포트는 이미 발행됐지만 이메일 발송 "
                      "기록이 없습니다(수동 재발행 등으로 자동 이메일 발송 절차를 건너뛰었을 "
                      "가능성). 필요 시 수동으로 이메일 발송 여부를 확인하세요.")
            continue

        import sources
        # 체크윈도우 시각대에는 "오늘의 KST 캘린더 날짜"가 곧 두 세션 모두의 기대 날짜와 같다.
        # (us: 미국장 마감일+1일=오늘, kr: 한국장 마감일=오늘)
        today_kst = now_sgt.astimezone(KST).date()

        if session == "kr":
            import calendars
            # kr 세션은 오늘 한국 증시가 실제로 열렸어야 '마감 브리핑'이 의미가
            # 있다. 그런데 아래 소스 매칭(_find_matching)은 날짜+시간대만 보고
            # 판정해서, 태그 없는 소스(버터대디)가 휴장일에 올린 무관한 글(예:
            # 일요일 주간 정리)이 그날 저녁 시간대에 올라오면 "오늘 kr 콘텐츠
            # 있음"으로 오판해 휴장일에도 발행·발송돼버린다(2026-08-16 실사고 —
            # 일요일에 금요일 마감 데이터로 리포트가 재발행·재발송됨). 그래서
            # 소스 매칭 여부와 무관하게, 오늘이 애초에 휴장일이면 여기서 바로
            # 건너뛴다.
            if calendars.is_kr_market_holiday(today_kst):
                print(f"[kr] 건너뜀 — {today_kst} 한국 증시 휴장일, 소스 매칭 확인 없이 스킵")
                if not dry_run:
                    _mark_done(session, date_str, "holiday_skip")
                continue

        src = sources.get_sources_for_label_date(today_kst, session)
        has_source = sources.has_any(src)
        is_hardstop = t >= hardstop

        if not has_source:
            # 하드스톱을 지났어도 버터대디/증시각도기 총평 원문이 아직 없으면
            # 규칙 기반(또는 웹서치) 대체 총평으로 발행하지 않고 계속 대기한다
            # — 대체 총평은 인사이트가 없어 가치가 낮다는 피드백. 휴장일이라
            # 애초에 원문이 안 올라올 상황일 때만 예외적으로 건너뛴다.
            if is_hardstop:
                import calendars
                # us 세션은 "어제(=market_date)가 미국 휴장일이었는지"가 아니라
                # "오늘(today_kst) 한국 증시가 열리는지"로 건너뛸지 판단한다.
                # 예전엔 어제 기준으로 봤는데, 주말 직후 월요일은 구조상 어제가
                # 항상 휴장일이라 "장전 리포트"(휴장 다음 첫 개장일 프리뷰,
                # briefing.py의 is_gap 분기 참고)까지 갈 필요도 없이 매주 조기
                # 스킵돼버리는 문제가 있었다(2026-08-10 실사고). 오늘 한국 증시가
                # 열리는 날이면 원문이 늦게라도 올라올 수 있으니 계속 대기하고,
                # 오늘도 한국 증시 휴장(연휴 등)이면 그때만 건너뛴다 — kr 세션은
                # 원래도 today_kst 기준이라 이 변경의 영향을 받지 않는다.
                market_date = today_kst if session == "kr" else today_kst - datetime.timedelta(days=1)
                if session == "kr":
                    is_holiday = calendars.is_kr_market_holiday(market_date)
                else:
                    is_holiday = calendars.is_kr_market_holiday(today_kst)
                if is_holiday:
                    print(f"[{session}] 건너뜀 — {market_date} 휴장일(주말/공휴일)이라 소스도 없음, 발송 생략")
                    if not dry_run:
                        _mark_done(session, date_str, "holiday_skip")
                    continue
                print(f"[{session}] 대기 중 — 하드스톱을 지났지만 원문이 아직 없어 계속 대기 (현재 {t})")
            else:
                print(f"[{session}] 대기 중 — 원천 콘텐츠 아직 없음 (윈도우 {start}~{hardstop}, 현재 {t})")
            continue

        reason = "source_ready"
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
                                     source_date=today_kst, require_narrative=True)
            if result.get("skipped") == "narrative_unavailable":
                # AI 총평 생성이 일시 실패한 경우 — 규칙 기반 대체로 발행하는 대신
                # (인사이트 없는 대체 총평은 가치가 낮다는 피드백) 마커를 남기지
                # 않고 다음 15분 주기에 다시 시도한다.
                print(f"[{session}] 대기 중 — 총평 생성 일시 실패, 다음 주기에 재시도")
                continue
            _mark_done(session, date_str, reason)
            if result.get("skipped"):
                # 예: 월요일 장전 리포트인데 오늘이 한국 증시 휴장일 — 열릴 장이
                # 없으니 발행·발송 없이 조용히 넘어간다(내일 다시 정상 판단됨).
                print(f"[{session}] 생략 — {result['skipped']} ({result.get('want_date')})")
                continue
            _, fn, pdf, report_url, viewer_url = result["outputs"][0]
            fired.append((session, reason, fn))
            if session == "us":
                # 2026-08-16: 비용 절감을 위해 미국장 세션은 리포트/사이트는
                # 계속 생성하되 이메일은 발송하지 않기로 함(사용자 결정) — 국내
                # 증시에만 집중. email_sent를 함께 마킹해 다음 체크에서 "이메일
                # 기록 없음" 경고가 반복해서 뜨지 않게 한다.
                print(f"[{session}] 이메일 발송 생략 — 미국장 세션은 이메일 미발송 정책")
                if not dry_run:
                    _mark_email_sent(session, date_str)
                continue
            if _already_published_upstream(session, date_str):
                # 이 실행이 빌드하는 동안 다른(거의 동시에 시작된) 트리거 실행이
                # 먼저 커밋·발송을 끝냈다 — 같은 리포트를 또 보내지 않는다.
                print(f"[{session}] 이메일 발송 생략 — 동시 실행된 다른 트리거가 이미 발행·발송함")
                continue
            if _send_report_email(result, viewer_url, session=session, date_str=date_str):
                _mark_email_sent(session, date_str)
                payload = _email_payload_path(session, date_str)
                if os.path.exists(payload):
                    os.remove(payload)
        else:
            fired.append((session, reason, None))
    return fired


def _send_report_email(result, viewer_url, session=None, date_str=None):
    """리포트가 처음 새로 발행될 때 이메일을 보낸다.

    자막 지연 반영 등으로 조용히 재발행되는 경우는 여기서 호출하지 않는다
    (사이트만 갱신, 이미 최초 발행 때 받은 메일을 또 보내면 스팸처럼
    느껴진다는 피드백).

    session/date_str가 주어지면 발송 시도 **전에** 이메일 내용을 디스크에
    저장한다 — 발송이 실패해도 다음 15분 주기 실행의 retry_unsent_emails()가
    리포트 재빌드 없이 재발송할 수 있게 하기 위함(자가치유).
    """
    import delivery
    try:
        subject = f"[{result['title']}] {result['ref']}"
        args = (result["title"], result["ref"], result["narr"], result["summary"], result["mc"])
        events = result.get("events")
        body = delivery.build_email_body(*args, link_url=viewer_url or "", events=events)
        html_body = delivery.build_email_html(*args, link_url=viewer_url or "", events=events)
        if session and date_str:
            _save_email_payload(session, date_str, subject, body, html_body)
        delivery.send_email(subject, body, [], html_body=html_body)
        print(f"  → 이메일 발송 완료 ({subject})")
        return True
    except Exception as e:
        print("  ! 이메일 발송 실패:", repr(e)[:200])
        return False


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
        still_pending, resolved, reasons = {}, False, []
        for pid, baseline_len in marker.get("pending", {}).items():
            post = sources.get_post_by_id(pid)
            rclen = len(post.get("raw_content") or "") if post else baseline_len
            if post and post.get("status") != "transcript_pending" and rclen > baseline_len + 100:
                resolved = True
                reasons.append("자막 반영")
            else:
                still_pending[pid] = baseline_len

        # 빌드 당시 아예 없었거나 분량 미달로 제외됐던 소스가 뒤늦게 발행됐는지도
        # 확인한다. 하드스톱(예: KR 19:00) 이후에야 올라오는 글 — 버터대디 한국장
        # 리캡이 21시대에 올라온 2026-07-22 실사례 — 은 자막 대기 감지만으로는
        # 영영 총평에 반영되지 않았다.
        still_missing = list(marker.get("missing_sources", []))
        if still_missing:
            want = datetime.date.fromisoformat(marker["source_date"])
            src_now = sources.get_sources_for_label_date(want, marker["session"])
            newly = [k for k in still_missing
                     if src_now.get(k) and len(src_now[k].get("raw_content") or "") >= 300]
            if newly:
                resolved = True
                reasons.append("늦게 발행된 원문 반영(" + ", ".join(newly) + ")")
                still_missing = [k for k in still_missing if k not in newly]

        if resolved:
            print(f"[재발행] {marker['session']} {marker['archive_date']} — {' · '.join(reasons)}, 리포트 갱신")
            src_date = datetime.date.fromisoformat(marker["source_date"])
            result = briefing.build(session=marker["session"], theme=marker.get("theme", "coinbase"),
                                     make_pdf=False, source_date=src_date,
                                     require_narrative=True)
            if result.get("skipped") == "narrative_unavailable":
                # 총평 생성이 일시적으로 실패 — 기존 발행본을 유지했고, 마커도
                # 남겨둬 다음 15분 주기 실행에서 다시 시도한다(단, 재시도 시한
                # 이 지나면 아래 else 분기 로직과 동일하게 포기·정리).
                elapsed_h = (now_sgt - datetime.datetime.fromisoformat(marker["first_seen"])).total_seconds() / 3600
                if elapsed_h >= PENDING_RETRY_HOURS:
                    os.remove(path)
                continue
            if result.get("skipped"):
                print(f"[재발행] 생략 — {result['skipped']}")
                os.remove(path)
                continue
            # 자막/AI-Tech가 뒤늦게 붙어 조용히 갱신하는 경우다 — 최초 발행 때 이미
            # 이메일을 받은 리포트라 매번 또 보내면 스팸처럼 느껴진다는 피드백으로,
            # 사이트만 갱신하고 이메일은 다시 보내지 않는다.
            updated.append((marker["session"], marker["archive_date"]))
            # briefing.build()가 이 재빌드 결과를 바탕으로 마커 파일 자체를 이미
            # 새로 쓰거나(다른 원천이 여전히 대기 중) 지웠으므로(전부 해결) 여기서
            # 다시 건드리지 않는다 — 안 그러면 재빌드 이전의 낡은 상태로 덮어써버린다.
            continue

        elapsed_h = (now_sgt - datetime.datetime.fromisoformat(marker["first_seen"])).total_seconds() / 3600
        if (still_pending or still_missing) and elapsed_h < PENDING_RETRY_HOURS:
            marker["pending"] = still_pending
            marker["missing_sources"] = still_missing
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
        # 이전 실행에서 발송에 실패한 이메일이 있으면 리포트 재빌드 없이 재발송
        retry_unsent_emails()
