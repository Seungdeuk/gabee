# 가비 소개 사이트 (정적 파일)

ChatGPT 같은 AI 검색과 일반 검색에 가비가 나오게 하려고 만든 소개 사이트입니다.
빌드 과정이 없습니다. 이 폴더의 파일을 그대로 올리면 됩니다.

| 파일 | 역할 |
|---|---|
| `index.html` | 소개 본문. 첫 화면, 기능 5가지(시연 화면), 가비 소개, 자주 묻는 질문, 영어 요약, 구조화 정보(JSON-LD) |
| `download/index.html` | 다운로드 페이지. 구글 플레이 버튼과 QR 코드, 설치 순서 |
| `assets/site.css`, `assets/site.js` | 두 페이지 공통 모양과 동작(기능 탭, 시연 재생) |
| `assets/gabee-mascot.png`, `assets/favicon.png` | 가비 캐릭터 그림, 파비콘 |
| `robots.txt` | 검색·AI 로봇(OAI-SearchBot, ChatGPT-User, GPTBot 등)에게 읽어도 된다고 알림 |
| `sitemap.xml` | 페이지 목록 |
| `llms.txt` | AI 가 읽기 쉬운 요약 |

## 내 PC 에서 보기
이 폴더에서 `python -m http.server 8799` 를 실행하고 브라우저에서 `http://127.0.0.1:8799/` 를 엽니다.

## 배포 (Cloudflare Pages, 아직 안 올림)
- 빌드가 없는 정적 파일이라 서버가 필요 없습니다.
- GitHub 연결로 만들 때: 빌드 명령은 비워 두고, 빌드 출력 폴더(Build output directory)를 `apps/site` 로 정합니다(화면 항목 이름은 올릴 때 다시 확인).
- 파일을 직접 올리는 방식(Drag and drop)으로 만든 프로젝트는 나중에 GitHub 연결로 바꿀 수 없습니다(Cloudflare 문서). 처음에 방식을 정합니다.
- 도메인: Pages 프로젝트의 Custom domains 에서 `gabee.cloud` 를 먼저 추가합니다. DNS 기록을 손으로 먼저 만들면 522 오류가 납니다. `api.gabee.cloud` 는 건드리지 않습니다.
- Cloudflare 의 AI 봇 차단 설정이 켜져 있으면 `robots.txt` 와 상관없이 ChatGPT 검색 봇이 막힙니다. 올린 뒤 확인합니다.

## 구글 플레이 연결
- 버튼과 QR 코드는 모두 구글 플레이의 가비 페이지(`com.kangminhun.gabee`)로 갑니다.
- 주소 뒤에 유입 경로 꼬리표가 붙어 있습니다. `utm_source=website` 이고, `utm_medium` 은 버튼 위치(`download`, `footer`, `qr`)입니다.
- QR 코드는 `download/index.html` 안에 그림(SVG)으로 들어 있습니다. 주소를 바꾸면 QR 도 다시 만들어야 합니다.

## 시연 화면
휴대폰 화면은 기능을 설명하려고 만든 예시입니다(실제 앱 녹화가 아닙니다). 화면에도 그렇게 적혀 있습니다.
실제 녹화 영상이 생기면 `index.html` 의 `phone demo` 자리를 `video` 태그로 바꾸면 됩니다.

## 주소를 바꿀 때
파일 안의 주소는 `https://gabee.cloud/` 로 적혀 있습니다. 다른 주소에 올리면
`index.html`, `download/index.html`, `robots.txt`, `sitemap.xml`, `llms.txt` 에서 `https://gabee.cloud` 를 새 주소로 모두 바꿉니다.

## 내용의 근거 (2026-11-18 확인)
- 구글 플레이 스토어의 가비 설명 문구, 가격(무료), 분류(라이프스타일), 기기(안드로이드)
- 앱스토어 조회 결과 아이폰용 없음
- 저장소의 공개 안내 페이지(`app/shared/public_pages`): 슬로건, 로그인 방법, 운영자

내용이 바뀌면(아이폰 출시, 기능 추가 등) 본문, JSON-LD, `llms.txt`, 꼬리말의 기준 날짜를 같이 고칩니다.
