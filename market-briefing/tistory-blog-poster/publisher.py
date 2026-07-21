# -*- coding: utf-8 -*-
"""
Playwright로 Tistory 편집기를 조작해 글을 발행한다.
  login_setup.py로 저장해둔 영구 프로필(쿠키/세션)을 재사용하므로 헤드리스로 동작한다.

Tistory Open API는 2024년초 완전 종료되어 API로는 글을 쓸 수 없다.
  대신 실제 에디터(KEditor/TinyMCE) DOM을 조작한다. 본문은
  tinymce.get('editor-tistory').setContent(html)로 주입한다 — 이 방식은
  에디터의 "기본모드/HTML모드" 전환 시 뜨는 네이티브 confirm() 다이얼로그를
  건드릴 필요가 없어 가장 안정적이다.

로그인 세션은 두 가지 방식 중 하나로 확보한다:
  1) storage_state.json — 실제 크롬(로그인된 세션)에서 Cookie-Editor 등으로 내보낸
     쿠키를 변환해 넣어둔 파일. 있으면 이걸 최우선으로 쓴다(카카오 봇 감지로 인한
     자동 로그인 실패를 우회).
  2) .auth/chrome-profile — login_setup.py로 만든 영구 프로필(자동 로그인 방식).
"""
import os, re, html, urllib.parse
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


def _full_res_url(thumb_css_url):
    """
    .box_thumb의 background-image는 img1.daumcdn.net/thumb/C170x170/?...&fname=<원본URL>
    형태의 170x170 축소 썸네일이다. 본문에 크게 보여줄 이미지로는 너무 작으므로,
    쿼리스트링에 인코딩되어 있는 원본(fname) URL을 꺼내 대신 쓴다.
    """
    parsed = urllib.parse.urlparse(thumb_css_url)
    qs = urllib.parse.parse_qs(parsed.query)
    fname = qs.get("fname")
    return fname[0] if fname else thumb_css_url


def _normalize(text):
    """
    태그/속성 차이(TinyMCE가 붙이는 data-ke-size 등)와 HTML 엔티티 인코딩 차이
    (예: "·" -> "&middot;")를 모두 흡수해서 순수 텍스트만 비교하기 위한 정규화.
    """
    no_tags = re.sub(r"<[^>]+>", "", text)
    return html.unescape(no_tags)


def _content_marker(body_html, length=60):
    """
    주의: marker가 너무 짧으면(예: 빈 문자열) `marker in text` 검사가 뭘 비교해도
    항상 True가 되어 "검증됨"이라는 거짓 안심을 준다 — 실제로 본문이 통째로 사라진
    사고가 이 허점 때문에 한 번 발생했다. 최소 길이를 강제해 이 클래스의 버그를 막는다.
    """
    marker = _normalize(body_html)[:length]
    if len(marker.strip()) < 20:
        raise RuntimeError(
            f"본문 내용이 비정상적으로 짧습니다(마커 길이 {len(marker.strip())}). "
            "body_html이 제대로 전달됐는지 확인하세요.")
    return marker

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(HERE, ".auth", "chrome-profile")
STORAGE_STATE_PATH = os.path.join(HERE, ".auth", "storage_state.json")
BLOG = "https://doleman.tistory.com"
NEWPOST_URL = f"{BLOG}/manage/newpost/"


def _insert_body_image_html(body_html, body_image_url, title):
    safe_alt = html.escape(f"{title} 핵심 흐름 설명 이미지", quote=True)
    figure = (f'<figure class="imageblock alignCenter"><img '
              f'src="{html.escape(body_image_url, quote=True)}" alt="{safe_alt}">'
              f'<figcaption>{safe_alt}</figcaption></figure>')
    enriched, count = re.subn(r"(</h[23]>)", r"\1" + figure,
                              body_html, count=1, flags=re.IGNORECASE)
    if count != 1:
        raise RuntimeError("본문 이미지 배치 지점을 찾지 못했습니다.")
    return enriched


def _upload_representative(page, image_path):
    """대표이미지 슬롯을 임시 CDN 업로더로 사용하고 원본 공개 URL을 반환한다."""
    if not os.path.isfile(image_path):
        raise RuntimeError(f"이미지 파일을 찾을 수 없습니다: {image_path}")
    file_input = page.locator(".box_thumb input[type=file]")
    if file_input.count() == 0:
        delete_button = page.locator(".box_thumb .ico_delete")
        if delete_button.count() != 1:
            raise RuntimeError("기존 대표이미지 제거 버튼을 찾지 못했습니다.")
        delete_button.click()
        page.wait_for_selector(".box_thumb input[type=file]", state="attached", timeout=10000)
    page.locator(".box_thumb input[type=file]").set_input_files(image_path)
    page.wait_for_selector(".box_thumb .thumb_g", state="visible", timeout=15000)
    bg = page.eval_on_selector(".box_thumb .thumb_g", "el => el.style.backgroundImage")
    match = re.search(r'url\("?(.*?)"?\)', bg)
    result = _full_res_url(match.group(1)) if match else None
    if not result:
        raise RuntimeError("Tistory CDN 이미지 URL을 확인하지 못했습니다.")
    return result


def publish_post(title, tags, body_html, category_id, thumbnail_path=None,
                 body_image_path=None, publish=True, headless=True):
    """
    반환: {"url": 발행된(또는 발행 직전 확인된) 글의 URL, "thumbnail_url": 업로드된
    대표이미지의 공개 URL(t1.daumcdn.net 등, 없으면 None)}
    publish=False면 마지막 '공개 발행' 클릭 직전까지만 진행하고 저장하지 않는다
    (내용 검증용 드라이런).
    thumbnail_path: 대표이미지로 업로드할 로컬 이미지 파일 경로(선택). 업로드에 성공하면
    반환값의 thumbnail_url을 video_maker.create_promo_video()나 threads_poster의
    image_url/video용 input_image_url로 재사용할 수 있다.
    """
    has_storage_state = os.path.isfile(STORAGE_STATE_PATH)
    has_profile = os.path.isdir(PROFILE_DIR)
    if not has_storage_state and not has_profile:
        raise RuntimeError(
            "로그인 세션이 없습니다. storage_state.json을 만들거나(쿠키 가져오기), "
            "`python login_setup.py`로 1회 로그인하세요.")

    with sync_playwright() as p:
        launch_kwargs = dict(
            headless=headless, viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        if has_storage_state:
            try:
                browser = p.chromium.launch(channel="chrome", headless=headless,
                                             args=launch_kwargs["args"])
            except Exception:
                browser = p.chromium.launch(headless=headless, args=launch_kwargs["args"])
            context = browser.new_context(
                storage_state=STORAGE_STATE_PATH, viewport={"width": 1280, "height": 900})
        else:
            try:
                context = p.chromium.launch_persistent_context(
                    PROFILE_DIR, channel="chrome", **launch_kwargs)
            except Exception:
                context = p.chromium.launch_persistent_context(PROFILE_DIR, **launch_kwargs)
        page = context.new_page()
        page.on("dialog", lambda d: d.accept())

        page.goto(NEWPOST_URL)
        page.wait_for_load_state("networkidle")
        if "auth/login" in page.url or "/login" in page.url:
            context.close()
            raise RuntimeError(
                "로그인 세션이 만료되었습니다. 실제 크롬에서 doleman.tistory.com에 로그인한 뒤 "
                "쿠키를 다시 내보내 storage_state.json을 갱신하거나(권장), "
                "`python login_setup.py`로 재로그인하세요.")

        # 카테고리 선택
        page.click("#category-btn")
        page.click(f"#category-item-{category_id}")

        # 제목
        page.fill("#post-title-inp", title)

        # 본문 — TinyMCE API로 직접 주입 (드롭다운/다이얼로그 우회)
        # 주의: setContent()만으로는 화면에만 반영되고, 실제 발행/저장은 TinyMCE가
        # 관리하는 숨은 <textarea id="editor-tistory">의 값을 읽어간다. 반드시
        # save()(=triggerSave)까지 호출해 그 textarea에 동기화해야 저장된다 —
        # 이걸 빠뜨려서 실제 발행 시 옛 내용(예: 이전 임시저장분)이 그대로 올라가는
        # 사고가 있었다.
        import structured_data
        current_body = structured_data.prepend_json_ld(
            body_html, title, image_url=None)
        page.wait_for_function(
            "() => window.tinymce && tinymce.get('editor-tistory')")
        page.evaluate(
            "(html) => { const ed = tinymce.get('editor-tistory'); ed.setContent(html); ed.save(); }",
            current_body)
        marker = _content_marker(current_body)
        synced = page.eval_on_selector("#editor-tistory", "el => el.value")
        if marker not in _normalize(synced):
            raise RuntimeError(
                "본문이 실제 저장용 textarea에 동기화되지 않았습니다. 발행을 중단합니다.")

        # 태그
        tag_input = page.locator("#tagText")
        for tag in tags:
            tag = tag.strip()
            if not tag:
                continue
            tag_input.click()
            tag_input.fill(tag)
            tag_input.press("Enter")

        # 발행 모달 열기
        page.click("#publish-layer-btn")
        page.wait_for_selector("#publish-btn", state="visible", timeout=10000)

        # 대표이미지 업로드 (모달 안 .box_thumb 안에 input[type=file]이 이미 존재).
        # 주의: 업로드 성공 시 <img> 태그가 아니라 .thumb_g의 background-image 스타일로
        # 표시된다. 그리고 이 "대표이미지"는 목록/공유용일 뿐 본문에는 자동으로 안 보이므로,
        # 실제로 글 안에 이미지가 보이게 하려면 URL을 뽑아서 본문 맨 앞에 <img>로 직접 넣어야 한다.
        thumbnail_url = None
        body_image_url = None
        if thumbnail_path:
            if not os.path.isfile(thumbnail_path):
                raise RuntimeError(f"썸네일 파일을 찾을 수 없습니다: {thumbnail_path}")
            # 본문 이미지도 외부 raw URL을 직접 쓰지 않고 Tistory CDN에 먼저 올린다.
            # 대표 슬롯에 본문 이미지를 임시 업로드해 URL을 얻고, 마지막에 대표를 올린다.
            if body_image_path:
                body_image_url = _upload_representative(page, body_image_path)
                page.locator(".box_thumb .ico_delete").click()
                page.wait_for_selector(".box_thumb input[type=file]", state="attached", timeout=10000)
            thumbnail_url = _upload_representative(page, thumbnail_path)

            if thumbnail_url:
                safe_alt = html.escape(title, quote=True)
                content_body = (_insert_body_image_html(body_html, body_image_url, title)
                                if body_image_url else body_html)
                enriched_body = structured_data.prepend_json_ld(
                    content_body, title, image_url=thumbnail_url)
                current_body = (
                    f'<img src="{thumbnail_url}" alt="{safe_alt}"><br>{enriched_body}')
                page.evaluate(
                    "(html) => { const ed = tinymce.get('editor-tistory'); ed.setContent(html); ed.save(); }",
                    current_body)
                marker = _content_marker(current_body)
                resynced = page.eval_on_selector("#editor-tistory", "el => el.value")
                if marker not in _normalize(resynced):
                    raise RuntimeError("본문에 대표이미지를 삽입한 뒤 동기화 검증에 실패했습니다.")

        if not publish:
            url = page.url
            context.close()
            return {"url": url, "thumbnail_url": thumbnail_url,
                    "body_image_url": body_image_url}

        # 발행 직전 최종 재확인 — 태그 입력/썸네일 업로드 등 중간 동작으로 에디터가
        # 초기화되는 경우를 대비해 저장용 textarea 내용을 다시 한번 검증한다.
        final_synced = page.eval_on_selector("#editor-tistory", "el => el.value")
        if marker not in _normalize(final_synced):
            page.evaluate(
                "(html) => { const ed = tinymce.get('editor-tistory'); ed.setContent(html); ed.save(); }",
                current_body)
            final_synced = page.eval_on_selector("#editor-tistory", "el => el.value")
            if marker not in _normalize(final_synced):
                context.close()
                raise RuntimeError("발행 직전 본문 동기화 검증에 실패했습니다. 발행을 중단합니다.")

        page.click("#publish-btn")
        try:
            page.wait_for_url(lambda u: "manage/newpost" not in u, timeout=15000)
        except PWTimeout:
            pass

        # 발행 직후 리다이렉트되는 곳은 관리자 글 목록(manage/posts/)이라 실제 공개
        # URL이 아니다 — 방금 올린 제목으로 글 목록에서 진짜 공개 링크를 찾아온다.
        public_url = None
        try:
            page.goto(f"{BLOG}/manage/posts/")
            page.wait_for_load_state("networkidle")
            public_url = page.eval_on_selector_all(
                "a",
                "(els, t) => { const m = els.find(a => a.textContent.includes(t)); return m ? m.href : null; }",
                title[:30],
            )
        except Exception:
            pass

        final_url = public_url or page.url
        context.close()
        return {"url": final_url, "thumbnail_url": thumbnail_url,
                "body_image_url": body_image_url}


def update_post_images(post_id, title, hero_path, body_image_path, headless=True):
    """기존 글의 레거시 첫 이미지를 새 대표이미지로 교체하고 본문 이미지를 추가한다."""
    if not os.path.isfile(hero_path):
        raise RuntimeError(f"대표이미지 파일을 찾을 수 없습니다: {hero_path}")
    if not os.path.isfile(body_image_path):
        raise RuntimeError(f"본문 이미지 파일을 찾을 수 없습니다: {body_image_path}")
    has_storage_state = os.path.isfile(STORAGE_STATE_PATH)
    if not has_storage_state:
        raise RuntimeError("Tistory storage_state.json 로그인 세션이 필요합니다.")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=headless,
                                        args=["--disable-blink-features=AutomationControlled"])
        except Exception:
            browser = p.chromium.launch(headless=headless,
                                        args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(storage_state=STORAGE_STATE_PATH,
                                      viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.on("dialog", lambda d: d.accept())
        page.goto(f"{BLOG}/manage/newpost/{post_id}?type=post&returnURL=%2Fmanage%2Fposts%2F")
        page.wait_for_load_state("networkidle")
        if "login" in page.url:
            raise RuntimeError("Tistory 로그인 세션이 만료되었습니다.")
        page.wait_for_function("() => window.tinymce && tinymce.get('editor-tistory')")
        current = page.evaluate("() => tinymce.get('editor-tistory').getContent()")

        page.click("#publish-layer-btn")
        page.wait_for_selector("#publish-btn", state="visible", timeout=10000)
        # 수정 글은 기존 대표이미지가 있으면 file input 대신 삭제 버튼만 보인다.
        # 기존 이미지를 먼저 제거해야 새 업로드 input이 생성된다.
        # 본문 이미지를 먼저 임시 대표로 업로드해 Tistory CDN URL을 얻는다.
        body_image_url = _upload_representative(page, body_image_path)
        page.locator(".box_thumb .ico_delete").click()
        page.wait_for_selector(".box_thumb input[type=file]", state="attached", timeout=10000)
        # 마지막 업로드가 실제 대표이미지가 된다.
        hero_url = _upload_representative(page, hero_path)

        safe_alt = html.escape(title, quote=True)
        hero_tag = f'<img src="{html.escape(hero_url, quote=True)}" alt="{safe_alt}">'
        if re.search(r"<img\b[^>]*>", current, flags=re.IGNORECASE):
            current = re.sub(r"<img\b[^>]*>", hero_tag, current, count=1,
                             flags=re.IGNORECASE)
        else:
            current = hero_tag + "<br>" + current
        # 깨진 외부 raw 본문 이미지는 제거한 뒤 CDN 이미지로 다시 삽입한다.
        current = re.sub(
            r'<figure[^>]*>\s*<img[^>]+raw\.githubusercontent\.com[^>]*>.*?</figure>',
            '', current, flags=re.IGNORECASE | re.DOTALL)
        if body_image_url not in current:
            body_alt = html.escape(f"{title} 핵심 흐름 설명 이미지", quote=True)
            body_tag = (f'<figure class="imageblock alignCenter"><img '
                        f'src="{html.escape(body_image_url, quote=True)}" alt="{body_alt}">'
                        f'<figcaption>{body_alt}</figcaption></figure>')
            current, inserted = re.subn(r"(</h[23]>)", r"\1" + body_tag,
                                        current, count=1, flags=re.IGNORECASE)
            if inserted != 1:
                raise RuntimeError("본문 이미지 배치 지점을 찾지 못했습니다.")
        page.evaluate(
            "(value) => { const ed=tinymce.get('editor-tistory'); ed.setContent(value); ed.save(); }",
            current)
        synced = page.eval_on_selector("#editor-tistory", "el => el.value")
        synced_unescaped = html.unescape(synced)
        if hero_url not in synced_unescaped or body_image_url not in synced_unescaped:
            raise RuntimeError("새 대표·본문 이미지가 저장 본문에 동기화되지 않았습니다.")
        page.click("#publish-btn")
        try:
            page.wait_for_url(lambda u: "manage/newpost" not in u, timeout=15000)
        except PWTimeout:
            pass
        context.close()
        return {"post_id": str(post_id), "hero_url": hero_url,
                "body_image_url": body_image_url}
