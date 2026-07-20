# -*- coding: utf-8 -*-
"""
doleman.tistory.com 자동 발행 (하루 4개 슬롯):
  us   — market-briefing 미국 증시 마감 브리핑 재작성
  kr   — market-briefing 한국 증시 마감 브리핑 재작성
  ai   — market-briefing/chatgpt-ai-tech의 AI·반도체·테크 오후 브리핑 재작성
  life — Claude가 직접 웹서치로 고른 실시간 생활정보/건강 트렌드 글 (외부유입용)

발행 후에는 기본적으로 Threads에 외부유입용 캡션을 자동 포스팅한다(--no-threads로 끌 수 있음).

사용:
  python main.py kr --threads-image-url URL  # 발행 + Threads 전용 4:5 이미지 포스팅
  python main.py us --dry-run          # 발행하지 않고 미리보기 HTML/썸네일만 저장
  python main.py ai                    # AI-Tech 오후 브리핑 기반 글 발행
  python main.py kr --no-thumbnail     # 대표이미지 없이 발행
  python main.py kr --no-threads       # Threads 포스팅 생략
  python main.py kr --video            # 발행 후 홍보영상 생성(고급, 아직 실험적)
  python main.py kr --pdf              # market-briefing 쪽 PDF 리포트도 함께 생성

사전 준비:
  1) pip install -r requirements.txt (playwright, anthropic, pillow, requests 등)
  2) playwright install chromium (최초 1회)
  3) 로그인 세션: .auth/storage_state.json(쿠키 가져오기, 권장) 또는
     python login_setup.py (자동 로그인, 카카오 봇 감지로 실패할 수 있음)
  4) (선택) .env 에 HIGGSFIELD_KEY 추가 — 없으면 썸네일은 그라디언트로 대체(정상 동작)
  5) .env 에 THREADS_ACCESS_TOKEN / THREADS_USER_ID 추가
     (threads_poster.py 상단 안내에 따라 Meta 개발자 앱 등록 후 발급)
"""
import argparse, os, sys, datetime

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
HERE = os.path.dirname(os.path.abspath(__file__))
MB_DIR = os.path.abspath(os.path.join(HERE, "..", "market-briefing"))
load_dotenv(os.path.join(HERE, ".env"))

SGT = datetime.timezone(datetime.timedelta(hours=8))


def _write_market_post(session, make_pdf):
    os.chdir(MB_DIR)
    sys.path.insert(0, MB_DIR)
    import briefing  # noqa: E402

    print(f"[1/4] market-briefing 데이터 수집 + 총평 생성 ({session})...")
    result = briefing.build(session=session, make_pdf=make_pdf)
    narr = result.get("narr")
    if not narr:
        print("총평(narrative) 생성에 실패했습니다. 원천 콘텐츠/데이터가 부족한 것으로 보입니다.")
        print("market-briefing/out 폴더의 리포트는 정상 생성되었을 수 있으니 확인해보세요.")
        return None, None

    sys.path.insert(0, HERE)
    import writer  # noqa: E402

    print("[2/4] doleman 블로그 스타일로 글 작성...")
    post = writer.write_post(result["session"], result["ref"], narr, result.get("summary"))
    return post, result["ref"]


def _write_ai_tech_post():
    os.chdir(MB_DIR)
    sys.path.insert(0, MB_DIR)
    import ai_tech  # noqa: E402

    today = datetime.datetime.now(SGT).date()
    print("[1/4] AI-Tech 오후 브리핑 확인...")
    # 오늘 오후판을 우선 사용하되, 아직 생성 전이면 오늘 오전판을 사용한다.
    # 어제 자료로 폴백하면 같은 사건을 제목만 바꿔 재발행하게 되므로 금지한다.
    markdown_text, file_date = ai_tech.get_ai_tech_markdown("kr", today)
    if not markdown_text:
        markdown_text, file_date = ai_tech.get_ai_tech_markdown("us", today)
    if not markdown_text:
        print("오늘 AI-Tech 브리핑을 찾지 못했습니다(오전/오후판 모두 없음).")
        return None, None
    print(f"  -> {file_date.isoformat()} 오늘자 브리핑 확인")

    sys.path.insert(0, HERE)
    import ai_writer  # noqa: E402

    print("[2/4] doleman 블로그 스타일로 글 작성...")
    post = ai_writer.write_post(markdown_text, file_date)
    return post, file_date.isoformat()


def _write_lifestyle_post():
    sys.path.insert(0, HERE)
    import lifestyle_writer  # noqa: E402

    today = datetime.datetime.now(SGT).date()
    print("[1/4] 실시간 생활정보/건강 트렌드 조사 + 글 작성...")
    try:
        import publication_state
        avoid_titles = publication_state.recent_titles()
    except Exception:
        avoid_titles = []
    post = lifestyle_writer.write_post(today, avoid_titles=avoid_titles, slot="life")
    return post, today.isoformat()


def run(session, dry_run, make_pdf, use_thumbnail, use_video, use_threads,
        force=False, threads_image_url=None):
    if session in ("us", "kr", "ai") and not os.path.isdir(MB_DIR):
        raise RuntimeError(f"market-briefing 폴더를 찾을 수 없습니다: {MB_DIR}")

    sys.path.insert(0, HERE)
    import publication_state
    today = datetime.datetime.now(SGT).date()
    if not dry_run and not force and publication_state.slot_done(today, session):
        print(f"오늘 {session} 슬롯은 이미 발행 완료되어 중복 실행을 건너뜁니다.")
        return

    fallback = False
    try:
        if session == "ai":
            post, ref = _write_ai_tech_post()
        elif session == "life":
            post, ref = _write_lifestyle_post()
        else:
            post, ref = _write_market_post(session, make_pdf)
    except Exception as e:
        print(f"  ! 기본 소재 생성 실패({repr(e)[:200]}) - SEO 대체 소재로 전환합니다.")
        post, ref = None, None

    if post is None or publication_state.is_duplicate(post.get("title", "")):
        reason = "기본 소재 없음" if post is None else "최근 발행 주제와 중복"
        print(f"[대체] {reason} - 실시간 검색 수요 기반 SEO 글을 생성합니다.")
        import lifestyle_writer
        post = lifestyle_writer.write_post(
            today,
            avoid_titles=publication_state.recent_titles(),
            slot=session,
        )
        ref = f"seo-{today.isoformat()}-{session}"
        fallback = True
        if publication_state.is_duplicate(post.get("title", "")):
            raise RuntimeError("SEO 대체 글도 최근 주제와 중복되어 안전하게 발행을 중단했습니다.")

    sys.path.insert(0, HERE)
    import ads, style, related_content, hub_content  # noqa: E402
    post["body_html"] = style.widen_line_height(post["body_html"])
    post["body_html"] = style.space_out_headings(post["body_html"])
    post["body_html"] = ads.insert_ads(post["body_html"])
    post["body_html"] = related_content.append_related_links(
        post["body_html"], post["title"], limit=3)
    post["body_html"] = hub_content.append_cluster(
        post["body_html"], post["title"], limit=5)
    print("  제목:", post["title"])
    print("  태그:", ", ".join(post["tags"]))

    thumbnail_path = None
    if use_thumbnail:
        print("[3/4] 대표이미지 생성...")
        import thumbnail
        thumbnail_path = thumbnail.make_thumbnail(
            post["title"],
            out_path=os.path.join(HERE, "out", f"thumb_{session}_{ref}.png"))
        print("  썸네일:", thumbnail_path)
    else:
        print("[3/4] 대표이미지 생성 건너뜀 (--no-thumbnail)")

    if dry_run:
        out_dir = os.path.join(HERE, "out")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"preview_{session}_{ref}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            img_tag = f'<img src="{thumbnail_path}" style="max-width:400px"><br>' if thumbnail_path else ""
            f.write(f"<h1>{post['title']}</h1>\n{img_tag}"
                    f"<p>태그: {', '.join(post['tags'])}</p>\n{post['body_html']}")
        print(f"[4/4] dry-run - 미리보기 저장: {out_path}")
        print("실제 발행/영상 생성/Threads 포스팅 없이 종료합니다.")
        return

    print("[4/4] Tistory에 발행 중...")
    import publisher
    pub = publisher.publish_post(
        post["title"], post["tags"], post["body_html"], post["category_id"],
        thumbnail_path=thumbnail_path)
    print("발행 완료:", pub["url"])
    publication_state.record(
        today, session, post["title"], pub["url"], source_ref=str(ref), fallback=fallback)
    if thumbnail_path and not pub.get("thumbnail_url"):
        print("  ! 대표이미지 업로드는 시도했으나 공개 URL을 확인하지 못했습니다.")

    if use_video:
        print("[영상] Higgsfield로 홍보영상 생성 중...")
        import video_maker
        video_path, _ = video_maker.create_promo_video(
            post["title"], post["body_html"], thumbnail_url=pub.get("thumbnail_url"))
        print("  영상 저장:", video_path)
        print("  ! Threads에 영상을 올리려면 이 영상이 공개 URL로 호스팅되어 있어야 합니다.")

    if use_threads:
        print("[Threads] 외부유입용 캡션 작성 + 포스팅 중...")
        try:
            import threads_writer, threads_poster
            caption_tpl = threads_writer.write_caption(post["title"], post["body_html"])
            campaign = f"tistory_{today.isoformat()}_{session}_hook"
            caption = threads_writer.finalize_caption(
                caption_tpl,
                pub["url"],
                campaign=campaign,
            )
            print("  캡션:", caption)
            if not threads_image_url:
                raise RuntimeError(
                    "Threads 전용 4:5 이미지 URL이 없습니다. 블로그 대표이미지는 재사용하지 않습니다. "
                    "--threads-image-url로 별도 제작 이미지를 지정하세요.")
            if threads_image_url == pub.get("thumbnail_url"):
                raise RuntimeError("Threads 이미지가 블로그 대표이미지와 같습니다. 전용 이미지를 사용하세요.")
            try:
                media_id = threads_poster.post_image(threads_image_url, caption)
            except Exception as image_err:
                raise RuntimeError(
                    f"Threads 이미지 게시 실패: {repr(image_err)[:160]}")
            print("  Threads 게시 완료, id:", media_id)
            import growth_state
            growth_state.record_threads(
                pub["url"], media_id, variant="question_hook", campaign=campaign)
        except Exception as e:
            # Threads 실패로 이미 끝난 블로그 발행 자체를 실패로 만들지 않는다.
            print(f"  ! Threads 포스팅 실패({repr(e)[:200]}) - 블로그 글은 정상 발행되었습니다.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="market-briefing -> doleman.tistory.com 자동 발행")
    ap.add_argument("session", choices=["us", "kr", "ai", "life"],
                     help="us=미국 증시 마감, kr=한국 증시 마감, ai=AI/반도체/테크 오후 브리핑, "
                          "life=실시간 생활정보/건강 트렌드(자체 웹서치)")
    ap.add_argument("--dry-run", action="store_true", help="발행하지 않고 미리보기 HTML/썸네일만 저장")
    ap.add_argument("--pdf", action="store_true", help="market-briefing PDF 리포트도 함께 생성(us/kr 전용)")
    ap.add_argument("--no-thumbnail", dest="thumbnail", action="store_false", help="대표이미지 생성 생략")
    ap.add_argument("--no-threads", dest="threads", action="store_false", help="Threads 포스팅 생략")
    ap.add_argument("--threads-image-url",
                    help="블로그 대표이미지와 별도로 제작·공개 호스팅한 Threads 전용 4:5 이미지 URL")
    ap.add_argument("--video", action="store_true", help="발행 후 홍보영상 생성(Higgsfield, 실험적)")
    ap.add_argument("--force", action="store_true",
                    help="이미 완료된 슬롯도 신규·비중복 글 테스트를 위해 1회 강제 실행")
    ap.set_defaults(thumbnail=True, threads=True)
    args = ap.parse_args()
    run(args.session, args.dry_run, args.pdf, args.thumbnail, args.video,
        args.threads, force=args.force, threads_image_url=args.threads_image_url)
