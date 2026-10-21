# gabee_orj

React Native(Expo) 앱 + FastAPI 서버 모노레포. 협업 규칙은 [CLAUDE.md](CLAUDE.md) 참고.

## 서버

```bash
cd server
python -m venv .venv && source .venv/Scripts/activate   # macOS/Linux: .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn src.main:app --reload     # http://localhost:8000/docs
pytest
```

## 앱

```bash
cd app
npm install
npx expo start
```
