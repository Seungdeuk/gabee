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
docker compose up --build         # PostgreSQL(pgvector) + API  →  http://localhost:8000/docs
```

DB 는 `pgvector/pgvector:pg16` 이미지를 쓰고, `127.0.0.1` 에만 포트를 연다(외부 공개 안 함). 서버가 시작할 때 `pgvector` 확장을 자동으로 켠다.

pgvector 설치 확인 (PowerShell, `.env` 의 값을 그대로 쓴다):

```powershell
docker compose exec db psql -U postgres -d gabee -c "SELECT * FROM pg_extension WHERE extname='vector';"
```

DB 연결 확인:

```powershell
docker compose ps                 # db 가 healthy 인지 확인
curl http://localhost:8000/health # {"status":"ok"} 면 API가 DB에 연결됨
```

Docker 없이 `uvicorn`으로 서버만 띄우면서 이 Postgres에 붙이려면 `apps/api/.env`의 `DATABASE_URL`을 `postgresql+psycopg://<POSTGRES_USER>:<POSTGRES_PASSWORD>@127.0.0.1:<POSTGRES_PORT>/<POSTGRES_DB>`로 바꾼다(기본값은 SQLite. `localhost`보다 `127.0.0.1`을 권장 — 아래 오류 참고).

자주 발생하는 오류:
- **포트 충돌(5432 가 이미 사용 중)**: 루트 `.env`의 `POSTGRES_PORT`를 다른 값(예: `5433`)으로 바꾸고 `docker compose up --build`를 다시 실행한다.
- **`.env`를 안 만들고 실행**: `POSTGRES_USER` 등이 빈 값이 되어 DB가 뜨지 않는다. `copy .env.example .env`를 먼저 한다.
- **이미 `postgres:16`(pgvector 없음)로 떠 있던 볼륨을 쓰던 경우**: 볼륨은 그대로 유지되고, 다음 `docker compose up` 때 이미지만 `pgvector/pgvector:pg16`으로 바뀌며 확장이 자동으로 켜진다. 데이터는 삭제되지 않는다.
- **Windows 에서 `localhost:5432`로 접속이 멈추거나 느린 경우**: IPv6(`::1`)로 먼저 시도하다가 지연될 수 있다. `localhost` 대신 `127.0.0.1`을 쓴다(Docker는 `127.0.0.1`에만 바인딩하므로 어차피 이게 맞는 주소다).

이 프로젝트의 DB/API 는 폴더명으로 컨테이너·볼륨·네트워크 이름이 접두사 처리되어, 다른 프로젝트의 PostgreSQL/Docker 볼륨과 자동으로 분리된다.

## 앱 (apps/mobile)

```bash
cd apps/mobile
npm install
npx expo start
```

서버에 붙이려면 `apps/mobile/.env` 에 `EXPO_PUBLIC_API_URL=http://<개발 PC 의 IP>:8000` 을 적는다(폰에서는 `localhost` 가 폰 자신이라 PC 의 IP 를 써야 한다). 주소가 없으면 임시 데이터로 화면만 동작한다.

원본 프로젝트를 참고하는 방법은 [docs/legacy/original-reference.md](docs/legacy/original-reference.md).
