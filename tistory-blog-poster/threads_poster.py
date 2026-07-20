# -*- coding: utf-8 -*-
"""
Meta Threads API로 자동 포스팅한다 (공식 API, 2024년부터 제공).

사전 준비(사용자가 직접 해야 함 — 계정 생성/앱 등록은 대행 불가):
  1) https://developers.facebook.com 에서 Meta 개발자 앱 생성
  2) 앱에 "Threads API" 제품 추가, 본인 Threads 계정으로 사용 권한 부여
  3) threads_basic, threads_content_publish 권한으로 access token 발급
  4) 단기 토큰 → 장기 토큰(60일) 교환, 만료 전 주기적으로 갱신 필요
     (공식 문서: https://developers.facebook.com/docs/threads)
  5) 아래 두 값을 tistory-blog-poster/.env 에 저장:
       THREADS_ACCESS_TOKEN=...
       THREADS_USER_ID=...   (본인 Threads user id)

미디어(이미지/영상)를 올리려면 Meta 서버가 직접 fetch할 수 있는 "공개 URL"이 필요하다
(로컬 파일 직접 업로드 불가). 이미 발행한 Tistory 글의 대표이미지 URL을 그대로 쓰거나,
영상은 GitHub Pages 등 공개 호스팅에 먼저 올린 뒤 그 URL을 넘길 것.
"""
import os, time, requests
from io import BytesIO
from PIL import Image
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

GRAPH_BASE = "https://graph.threads.net/v1.0"
POLL_INTERVAL_SEC = 5
POLL_TIMEOUT_SEC = 300


def validate_threads_image(image_url):
    """공개 접근성·이미지 형식·4:5 세로 비율을 게시 전에 강제 검증한다."""
    r = requests.get(image_url, timeout=30)
    r.raise_for_status()
    content_type = r.headers.get("Content-Type", "").lower()
    if not content_type.startswith("image/"):
        raise RuntimeError(f"Threads 이미지 URL이 이미지가 아닙니다: {content_type}")
    if len(r.content) < 20_000:
        raise RuntimeError("Threads 이미지 파일이 비정상적으로 작습니다.")
    with Image.open(BytesIO(r.content)) as img:
        width, height = img.size
        ratio = width / height
        if height <= width or not 0.76 <= ratio <= 0.84:
            raise RuntimeError(
                f"Threads 이미지는 4:5 세로형이어야 합니다(현재 {width}x{height}).")
    return {"width": width, "height": height, "content_type": content_type}


def _creds(access_token=None, user_id=None):
    token = access_token or os.getenv("THREADS_ACCESS_TOKEN")
    uid = user_id or os.getenv("THREADS_USER_ID")
    if not token or not uid:
        raise RuntimeError(
            "THREADS_ACCESS_TOKEN / THREADS_USER_ID가 설정되어 있지 않습니다. "
            "threads_poster.py 상단 안내에 따라 Meta 개발자 앱을 먼저 등록하세요.")
    return token, uid


def _wait_container_ready(creation_id, token):
    deadline = time.time() + POLL_TIMEOUT_SEC
    while time.time() < deadline:
        r = requests.get(f"{GRAPH_BASE}/{creation_id}",
                          params={"fields": "status,error_message", "access_token": token}, timeout=30)
        r.raise_for_status()
        data = r.json()
        status = data.get("status")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"미디어 컨테이너 처리 실패: {data.get('error_message', data)}")
        time.sleep(POLL_INTERVAL_SEC)
    raise TimeoutError(f"미디어 컨테이너 처리 타임아웃 (creation_id={creation_id})")


def _publish(creation_id, token, user_id):
    r = requests.post(f"{GRAPH_BASE}/{user_id}/threads_publish",
                       params={"creation_id": creation_id, "access_token": token}, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def post_text(text, access_token=None, user_id=None):
    """텍스트만 있는 가장 단순한 포스트(호스팅 불필요)."""
    token, uid = _creds(access_token, user_id)
    r = requests.post(f"{GRAPH_BASE}/{uid}/threads",
                       params={"media_type": "TEXT", "text": text, "access_token": token}, timeout=30)
    r.raise_for_status()
    creation_id = r.json()["id"]
    return _publish(creation_id, token, uid)


def post_image(image_url, text, access_token=None, user_id=None):
    """검증된 Threads 전용 4:5 이미지 + 캡션을 게시한다."""
    validate_threads_image(image_url)
    token, uid = _creds(access_token, user_id)
    r = requests.post(f"{GRAPH_BASE}/{uid}/threads", params={
        "media_type": "IMAGE", "image_url": image_url, "text": text, "access_token": token,
    }, timeout=30)
    r.raise_for_status()
    creation_id = r.json()["id"]
    _wait_container_ready(creation_id, token)
    return _publish(creation_id, token, uid)


def post_video(video_url, text, access_token=None, user_id=None):
    """영상 + 캡션. video_url은 공개적으로 fetch 가능한 URL이어야 한다."""
    token, uid = _creds(access_token, user_id)
    r = requests.post(f"{GRAPH_BASE}/{uid}/threads", params={
        "media_type": "VIDEO", "video_url": video_url, "text": text, "access_token": token,
    }, timeout=30)
    r.raise_for_status()
    creation_id = r.json()["id"]
    _wait_container_ready(creation_id, token)
    return _publish(creation_id, token, uid)
