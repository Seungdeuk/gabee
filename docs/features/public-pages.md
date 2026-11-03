# 구현 현황: 공개 안내 페이지 (shared/public_pages)

구글 로그인 동의 화면 등 외부 서비스가 요구하는 공개 주소(홈페이지·개인정보처리방침·약관)용이다. 서버 기능이 아니라 `app/shared` 의 공통 코드다.

## 구현된 것 (`apps/api/app/shared/public_pages`)
- `GET /`(서비스 소개), `GET /privacy`(개인정보처리방침), `GET /terms`(서비스 약관): 로그인·DB 없이 고정 HTML 을 돌려준다. `include_in_schema=False` 라 `openapi.json` 에는 없다. `Cache-Control: public, max-age=300`, `X-Content-Type-Options: nosniff`.
- `layout.py`: 공통 HTML 틀(밝은/어두운 모드, 모바일 폭). `pages.py`: 본문. 본문은 코드에서 확인한 사실만 쓴다(조사한 근거: 사용자 모델·소셜 로그인·LLM 래퍼·위치 7일 보관 등).
- 문의 이메일은 설정 `SUPPORT_EMAIL`(`.env.example`)에서 읽어 꼬리말에 보인다(비우면 안 보인다). 값은 이스케이프해 넣는다.

## 공개 전에 채워야 하는 것 (화면에 노란 "확정 필요" 표시로 남아 있다)
운영 주체 명칭, 시행일, 항목별 보관 기간·파기 방법, 탈퇴(계정 삭제) 절차(앱에 계정 삭제 기능이 없다), 위탁·국외 이전 상세(Anthropic·TypeSafe·메일 업체·호스팅의 국가), 개인정보 보호책임자, 마이크 사용 여부, 위치 기능 제공 여부(안드로이드는 위치 권한이 막혀 있다), 소셜 로그인·주소 변환 서비스의 국가, 만 14세 미만 정책, 문의 이메일(`SUPPORT_EMAIL`). 모두 `pages.py` 의 `_todo(...)` 자리다.

## 시험
`app/shared/public_pages/tests/test_public_pages.py`: 로그인 없이 200·HTML(HEAD 포함), 보안 헤더, 명세에 없음, 핵심 고지 포함, 확정 필요 표시가 눈에 띄는지, 문의 이메일 설정·이스케이프.
