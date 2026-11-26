# GaBee — 가족용 AI 비서 앱

가족이 함께 쓰는 비서 앱입니다. AI 채팅, 가족 소통(채팅), 일정, 지갑(가계·정산), 마이 탭으로 구성되고, 가족방에서 `@가비`를 부르면 대화·일정·문서를 근거로 답합니다.
5명이 함께 개발한 팀 프로젝트이며, 이 저장소는 팀 저장소의 개인 보관용 복사본입니다.

> **최신 코드는 [`release/1.4`](https://github.com/Seungdeuk/gabee/tree/release/1.4) 브랜치에 있습니다.** `main`은 2026-11-06 시점이라 아래에 소개하는 Agent 평가 체계·타임라인 등은 `release/1.4`에서 확인할 수 있습니다.
> PR 번호는 팀 저장소 기준입니다. 모든 평가 수치는 합성 데이터 기준이며 실제 사용자 데이터로 측정한 값이 아닙니다.

## 기술 스택

| 영역 | 사용 기술 |
|---|---|
| 앱 | React Native (Expo SDK 54, Expo Router), JavaScript |
| 서버 | Python, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic |
| DB | PostgreSQL + pgvector |
| AI | Claude API, LangGraph(Main·하위 Agent 도구 호출), KoELECTRA NER, SigLIP2, ONNX Runtime(CPU) |
| 배포 | Docker, Cloud Run, EAS Build |

## 구조

```
apps/mobile/   React Native 앱 (features/ 기능별 코드, theme/ 디자인 토큰)
apps/api/      FastAPI 서버 (features/<기능>/ router → service → repository, shared/ 인증·LLM·개인정보)
apps/api/evals/agent_eval/   Agent Tool Calling 평가 체계 (release/1.4)
docs/          요구사항, 기능 현황, ADR(기술 결정 기록), API 계약(openapi.json)
```

AI는 Main Agent가 질문을 받아 소통·일정·정산 하위 Agent에게 도구 호출로 위임하는 구조입니다. 외부 LLM으로 보내기 전 가족 이름 같은 개인정보는 서버에서 가명화하고, 답을 받은 뒤 복원합니다.

## 팀 구성과 담당

| 담당 | 영역 |
|---|---|
| kangminhun (팀장) | AI 채팅·문서 RAG, Main·하위 Agent 연결과 LangGraph 공통 루프 |
| hellobk121 | 일정·일정 Agent, 놀이 탭 가비 추천 |
| hojenn24 | 정산·돌봄과 해당 Agent, 탭 Agent 평가 사례 |
| bobstealer | 관리자 화면·데이터 분석, 소개 사이트 |
| **Seungdeuk (본인)** | **Agent Tool Calling 평가 체계, 한국어 NER 개인정보 가명화, 소통(가족 채팅) 기능, 가족 타임라인·사진 판별** |

## 내가 한 일

팀 저장소에 병합된 PR 535개 중 317개를 작성했습니다. 주요 작업은 다음과 같습니다.

### 1. Agent Tool Calling 평가 체계 설계·구현

LLM Agent가 "맞는 도구를, 맞는 인자로, 안전하게" 부르는지 수치로 확인할 방법이 없어 평가 체계를 처음부터 만들었습니다(평가 PR 49개, 평가 코드의 99.7%를 직접 작성).

- **두 가지 실행 방식.** 실제 모델 없이 정해진 응답으로 도는 결정론적 Fake Runner와 실제 Claude를 부르는 Real Runner를 분리했습니다. 외부 API 호출 없이 개발 평가셋 36/36 통과, 기존 탭 Agent 평가 52사례를 옮겨 채점 조건 748/748 일치를 확인했습니다.
- **채점.** 합성 가족 DB·시드·사례·프롬프트 해시를 고정하고 Task Success, Tool Precision/Recall, Argument Accuracy, 보안 위반, 토큰·지연·비용을 채점합니다.
- **비용·보안 안전장치.** 실호출 전 9항목 사전 점검(Preflight), 비용 사전 승인과 예산 상한, 보안 위반이 나오면 다음 실행을 바로 멈추는 장치를 넣었습니다.
- **통합 실모델 평가 (36사례 × 3회).** Task Success 84.3%(91/108) → 90.6%(96/106, 미실행 2회를 실패로 보면 88.9%), Tool Precision 70.0% → 74.3%, P50 응답 5.63초 → 4.55초. 108회 실평가 비용 $0.38(승인 한도 $3.70). 개선 PR 15개 중 9개(라우팅 지침·되묻기·출력 상한·권한 필터)를 직접 작성했고 나머지는 팀원의 일정 Agent 개선입니다.
- **실패 분석.** 낮은 Precision의 원인이 불필요한 이중 호출 증가(6 → 12건)임을 찾았고, 프롬프트 보정이 6건 중 1건을 남기자 병합하지 않고 서버 측 라우팅 제한 설계로 전환했습니다(설계 단계). 평가 중 보안 위반이 감지되자 자동 중단 후 채점기 오탐으로 분석했지만 공식 기록은 바꾸지 않았습니다.
- **권한 격리 결함 수정 (#543).** 평가 중 가족방 일정 Agent가 질문자 개인 권한으로 조회해 비공개 일정 제목이 노출될 수 있는 문제를 발견하고, 방 구성원 모두가 볼 수 있는 항목만 모델에 넘기도록 고쳤습니다.

### 2. 한국어 NER 개인정보 가명화

- 서버 기준 개인정보 가명화 모듈과 합성 평가(#73), 개인정보 탐지 평가 데이터와 NER 학습·평가·ONNX 내보내기 코드(#207, #208)를 만들었습니다.
- KoELECTRA-small NER을 개선해 봉인 합성 평가 2,350문장에서 이름 노출률 17.07% → 10.23%, Exact F1 80.98 → 87.37을 측정했습니다. 사전 등록한 교체 기준에는 못 미쳐 판정은 기존 모델 유지입니다. 연구 전 과정은 [gabee-ner-research](https://github.com/Seungdeuk/gabee-ner-research)에 정리했습니다.
- 서비스 적용 준비(#528): 모델 해시 검사, NER 장애 시 외부 LLM 호출 차단(503)과 시험을 구현했습니다(운영 배포 전).
- 소통·정산 Agent 질문 속 가족 이름을 가명화하고 도구 인자는 실행 직전에만 복원(#456), 가족 AI 동의가 있을 때만 외부 AI를 부르는 관문(#544)을 넣었습니다.

### 3. 소통(가족 채팅) 기능과 소통 Agent 고도화

- 가족 채팅 AI 대화 분석(구조화 출력·캐시·호출 한도·동시 실행 방지)과 `@가비` 문서 검색(#48), 문서 검색의 올린 날·올린 사람 필터(#393, #553)를 구현했습니다.
- 평가에서 찾은 소통 Agent 실패를 고쳤습니다: 응답 잘림(#439), 다른 가족방 정보 요청(#489), 특정 글 질문의 분석 오용(#490).
- 소통 Agent 단독 실모델 평가(20사례 × 3회): Task Success 56/60, 보안 위반·프롬프트 인젝션 성공 0건, P50 4.5초, 질문당 $0.0017.
- 채팅 UI, 안 읽은 수 배지, `@가비` 답 공유, 1:1 방 `@가비`, 소통 푸시 알림, 채팅 사진을 문서함에 저장·빼기 등 화면 기능도 맡았습니다.

### 4. 가족 타임라인·사진 판별

- 날짜별 가족 타임라인 MVP(#546)와 AI 추억 후보 저장·조회·생성 요청 흐름(#481 ~ #492)을 만들었습니다. 자동 후보 기능은 기본 꺼짐으로 두고 동의 조건 뒤에 배치했습니다.
- 가족방 사진의 문서/일반 판별을 SigLIP2 ONNX(CPU)로 연결하고(#507), 로컬 OCR 의존성을 걷어냈습니다(#545). 운영과 같은 1 vCPU / 2GiB Docker에서 12장 동시 업로드 시 OOM 없이 최대 메모리 약 1,055MiB를 확인했습니다.

### 5. 개발 환경·보안

- 테스트 전용 SQLite 설정으로 전체 API 테스트 시간을 3시간 52분 → 24분으로 줄였습니다(#509).
- 외부 사진 주소 다운로드의 SSRF 방어(#512), 공용 DB 마이그레이션 반영용 Pull Agent(#25)를 만들었습니다.

## 실행 방법

개발 환경 설정(서버·Docker·Alembic·앱 실행)은 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)에 있습니다. 협업 규칙은 [CLAUDE.md](CLAUDE.md), [CONTRIBUTING.md](CONTRIBUTING.md)를 참고하세요.

```bash
# 서버
cd apps/api && pip install -e ".[dev]" && uvicorn app.main:app --reload
# 앱
cd apps/mobile && npm install && npx expo start
```
