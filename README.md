# family-secretary

가족용 비서 앱. React Native (Expo) + FastAPI 모노레포. 협업 규칙은 [CLAUDE.md](CLAUDE.md), [CONTRIBUTING.md](CONTRIBUTING.md) 참고.

## 브랜치와 맡는 기능

| 브랜치 | 맡는 기능 |
|---|---|
| `ai_assistant-ingest` | AI 비서 정제화: 원본 전처리, 자동 분류 |
| `ai_assistant-knowledge` | AI 비서 최적화: 데이터화, 벡터 DB |
| `schedule` | 일정 |
| `family_chat` | 소통(가족 채팅) |
| `billing-care` | 가계, 돌봄 |

## 서버 (apps/api)

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\activate            # cmd. Git Bash: source .venv/Scripts/activate / macOS·Linux: source .venv/bin/activate
pip install -e ".[dev]"
copy .env.example .env            # macOS·Linux·Git Bash: cp
uvicorn app.main:app --reload     # http://localhost:8000/docs
pytest
```

## docker 로 서버 + DB 실행

```bash
copy .env.example .env            # 값(DB 비밀번호 등)을 채운다
docker compose up --build         # PostgreSQL + API  →  http://localhost:8000/docs
```

## 앱 (apps/mobile)

```bash
cd apps/mobile
npm install
npx expo start
```

서버에 붙이려면 `apps/mobile/.env` 에 `EXPO_PUBLIC_API_URL=http://<개발 PC 의 IP>:8000` 을 적는다(폰에서는 `localhost` 가 폰 자신이라 PC 의 IP 를 써야 한다). 주소가 없으면 임시 데이터로 화면만 동작한다.

원본 프로젝트를 참고하는 방법은 [docs/legacy/original-reference.md](docs/legacy/original-reference.md).
