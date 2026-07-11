import os
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

from db.db import get_kakao_tokens, save_kakao_tokens

load_dotenv()

KAKAO_REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY")
KAKAO_REDIRECT_URI = os.environ.get("KAKAO_REDIRECT_URI", "http://localhost:5000/oauth/callback")
KAKAO_CLIENT_SECRET = os.environ.get("KAKAO_CLIENT_SECRET")

AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"


def _save_token_response(token_data: dict):
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])).isoformat()
    save_kakao_tokens(
        access_token=token_data["access_token"],
        refresh_token=token_data["refresh_token"],
        expires_at=expires_at,
    )


def _with_client_secret(data: dict) -> dict:
    if KAKAO_CLIENT_SECRET:
        data["client_secret"] = KAKAO_CLIENT_SECRET
    return data


def request_initial_tokens():
    """최초 1회: 브라우저에서 인가 코드를 발급받고, Access/Refresh Token으로 교환해 저장한다."""
    auth_url = (
        f"{AUTHORIZE_URL}?client_id={KAKAO_REST_API_KEY}"
        f"&redirect_uri={KAKAO_REDIRECT_URI}&response_type=code&scope=talk_message"
    )
    print("아래 URL을 브라우저에서 열어 카카오 로그인 및 동의를 진행하세요:")
    print(auth_url)
    code = input("리디렉션된 URL의 'code=' 뒤에 있는 인가 코드를 입력하세요: ").strip()

    resp = requests.post(
        TOKEN_URL,
        data=_with_client_secret({
            "grant_type": "authorization_code",
            "client_id": KAKAO_REST_API_KEY,
            "redirect_uri": KAKAO_REDIRECT_URI,
            "code": code,
        }),
        timeout=10,
    )
    resp.raise_for_status()
    _save_token_response(resp.json())
    print("토큰 저장 완료")


def refresh_access_token() -> dict:
    """만료된 access_token을 refresh_token으로 재발급하여 저장한다."""
    tokens = get_kakao_tokens()
    if not tokens:
        raise RuntimeError("저장된 카카오 토큰이 없습니다. request_initial_tokens()를 먼저 실행하세요.")

    resp = requests.post(
        TOKEN_URL,
        data=_with_client_secret({
            "grant_type": "refresh_token",
            "client_id": KAKAO_REST_API_KEY,
            "refresh_token": tokens["refresh_token"],
        }),
        timeout=10,
    )
    resp.raise_for_status()
    token_data = resp.json()

    if "refresh_token" not in token_data:
        token_data["refresh_token"] = tokens["refresh_token"]

    _save_token_response(token_data)
    return get_kakao_tokens()


if __name__ == "__main__":
    request_initial_tokens()
