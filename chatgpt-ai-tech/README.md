# AI·반도체·테크 데일리 브리핑

GitHub Actions가 OpenAI Responses API의 웹 검색 도구를 사용해 한국어 뉴스
브리핑을 생성합니다. 매일 Asia/Singapore 기준 오전 06:30과 오후 16:00에
실행되며, 결과는 `chatgpt-ai-tech/daily/YYYY-MM-DD-{edition}.md`에 저장됩니다.
이미 존재하는 브리핑은 덮어쓰지 않습니다.

## 설정

1. GitHub 저장소의 **Settings → Secrets and variables → Actions → Secrets**에서
   `OPENAI_API_KEY`라는 Repository secret을 만들고 OpenAI API 키를 저장합니다.
2. 선택 사항으로 같은 화면의 **Variables** 탭에서 `OPENAI_MODEL` Repository
   variable을 만듭니다. 설정하지 않으면 `gpt-5.6-terra`를 사용합니다.
3. 저장소의 **Settings → Actions → General → Workflow permissions**에서
   **Read and write permissions**를 선택합니다. 워크플로 자체도
   `contents: write` 권한을 선언합니다.

API 키를 파일, 커밋, 로그에 직접 넣지 마세요.

## 수동 테스트

1. GitHub의 **Actions** 탭에서 **AI & Technology Briefing**을 선택합니다.
2. **Run workflow**를 누릅니다.
3. `morning` 또는 `afternoon`을 선택한 뒤 실행합니다.
4. 실행 로그에서 생성 및 커밋 단계를 확인하고,
   `chatgpt-ai-tech/daily/` 아래에 오늘 날짜의 파일이 추가되었는지 확인합니다.

같은 날짜와 판을 다시 실행하면 기존 파일 보호를 위해 실패하는 것이 정상입니다.
오후판은 같은 날짜의 오전판을 프롬프트에 포함해, 중대한 후속 변화가 없는 반복
기사를 제외합니다.

## 일정

GitHub Actions cron은 UTC를 사용하므로 다음과 같이 변환되어 있습니다.

- `30 22 * * *`: 다음 날 06:30 Asia/Singapore
- `0 8 * * *`: 같은 날 16:00 Asia/Singapore

GitHub의 예약 실행은 서비스 부하에 따라 몇 분 늦게 시작될 수 있습니다.
