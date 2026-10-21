# family-secretary

가족용 비서 앱. React Native (Expo) + FastAPI 모노레포. 협업 규칙은 [CLAUDE.md](CLAUDE.md), [CONTRIBUTING.md](CONTRIBUTING.md) 참고.

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

## 앱 (apps/mobile)

```bash
cd apps/mobile
npm install
npx expo start
```
