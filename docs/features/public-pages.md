# 구현 현황: 공개 안내 페이지 (shared/public_pages)

구글 로그인 동의 화면 등 외부 서비스가 요구하는 공개 주소(홈페이지·개인정보처리방침·약관)용이다. 서버 기능이 아니라 `app/shared` 의 공통 코드다.

## 구현된 것 (`apps/api/app/shared/public_pages`)
- `GET /`(서비스 소개), `GET /privacy`(개인정보처리방침), `GET /terms`(서비스 약관): 로그인·DB 없이 고정 HTML 을 돌려준다. `include_in_schema=False` 라 `openapi.json` 에는 없다. `Cache-Control: public, max-age=300`, `X-Content-Type-Options: nosniff`.
- `layout.py`: 공통 HTML 틀(밝은/어두운 모드, 모바일 폭). `pages.py`: 본문. 본문은 코드에서 확인한 사실만 쓴다(조사한 근거: 사용자 모델·소셜 로그인·LLM 래퍼·위치 7일 보관 등).
- 문의 이메일은 설정 `SUPPORT_EMAIL`(`.env.example`)에서 읽어 꼬리말에 보인다(비우면 안 보인다). 값은 이스케이프해 넣는다.

## 팀원 방침과의 관계
팀원이 만든 GitHub Pages 방침 v0.1(`kangminhun.github.io/gabee-privacy/`)의 값(운영 주체 강민훈, 문의 이메일 삭제 요청 절차, 만 14세 미만 미수용, 위치 미수집, 위탁업체 Anthropic·Supabase·Google Cloud)을 합쳤다. 계정·데이터 삭제는 팀원의 `delete-account.html` 로 연결한다(이메일 접수). 본문은 코드 기준으로 더 상세하다(카카오 로그인, IP 주소 기록, TypeSafe 문서 분류, AI 가리기 처리의 한계, AI 사용 기록 90일).

## 정해진 값
시행일 2026년 11월 3일(`EFFECTIVE_DATE`), 개인정보 보호책임자 백승득(`PRIVACY_OFFICER`), 운영 주체 강민훈(`OPERATOR`). 마이크는 권한만 선언돼 있고 현재 사용하지 않으며, 음성 기능은 온디바이스로 제공할 예정이라고 적었다. 해외 이전 국가는 팀원 방침과 같이 "확인되는 대로 적는다"고 썼다. 문구가 바뀌면 `EFFECTIVE_DATE` 도 같이 고친다. 운영 서버 환경변수 `SUPPORT_EMAIL` 을 설정해야 문의 이메일이 꼬리말에 보인다.

## 시험
`app/shared/public_pages/tests/test_public_pages.py`: 로그인 없이 200·HTML(HEAD 포함), 보안 헤더, 명세에 없음, 핵심 고지 포함, 확정 필요 표시가 남아 있지 않은지·핵심 값(시행일·보호책임자·온디바이스), 문의 이메일 설정·이스케이프.
