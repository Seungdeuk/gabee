"""찰칵 가비 추천의 외부 호출 구조 시험(L0, 외부 호출 없음).

`test_security_matrix.py` 의 외부 호출 목록(OUTBOUND_FILES·LLM_*)에 사진 추천 파일 3개를 사유와 함께 올렸다. 목록에 올리는 것만으로는 아무것도 보장하지 않으므로,
그 사유가 실제 코드 구조와 맞는지 여기서 고정한다:
- 가족 사진을 AI 에 보내는 `photo_rec_ai.content_question` 은 `photo_rec._ask_content` 의 `call` 안에서만, 그 `call` 은 `ai_guard.run(call=...)` 로만 불린다.
- 공개 사진만 보내는 자동 보충 경로(`photo_rec_auto_ai`)는 가족·사용자 정보를 불러오지 않고, 고정 프롬프트와 사진 한 장만 보내며, 호출 수는 호출자의 기본 꺼짐 설정·하루 목표·시도 상한이 묶는다.
- Pixabay 클라이언트는 고정 검색어 목록과 API 키만 보내고, 호출자는 `photo_rec_auto` 하나다.
"""

import ast
from pathlib import Path
from types import SimpleNamespace

from app.features.play import photo_rec_auto_ai as auto_ai
from app.shared.config import Settings

APP_DIR = Path(__file__).resolve().parents[1] / "app"
PLAY = APP_DIR / "features" / "play"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _app_files() -> dict[str, str]:
    out = {}
    for path in APP_DIR.rglob("*.py"):
        rel = path.relative_to(APP_DIR).as_posix()
        if "/tests/" in rel:
            continue
        out[rel] = path.read_text(encoding="utf-8")
    return out


def _is(node: ast.AST, dotted: str) -> bool:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts)) == dotted


# ---- 가족 사진 → AI: 관문 안에서만 --------------------------------------------------------------------------------------------
def test_family_photo_ai_is_only_called_inside_the_ai_guard_call():
    tree = _tree(PLAY / "photo_rec.py")
    guarded: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is(node.func, "ai_guard.run"):
            for kw in node.keywords:
                if kw.arg == "call" and isinstance(kw.value, ast.Name):
                    guarded.add(kw.value.id)
    assert guarded == {"call"}, "ai_guard.run 의 call 은 하나여야 한다"
    inside = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in guarded]
    assert len(inside) == 1
    uses = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Name) and n.id == "content_question" and isinstance(n.ctx, ast.Load)
    ]
    assert uses, "content_question 을 쓰는 곳이 있어야 이 시험이 의미가 있다"
    covered = {id(n) for n in ast.walk(inside[0])}
    assert all(id(n) in covered for n in uses), "content_question 이 관문의 call 밖에서 불린다"


def test_no_other_app_code_calls_the_family_photo_ai():
    users = {rel for rel, text in _app_files().items() if "content_question" in text} - {
        "features/play/photo_rec_ai.py"
    }
    assert users == {"features/play/photo_rec.py"}


# ---- 공개 사진 → AI(자동 보충): 가족 정보 없이, 상한 안에서 --------------------------------------------------------------------
def test_the_auto_ai_module_loads_no_family_or_user_data():
    imported = set()
    for node in ast.walk(_tree(PLAY / "photo_rec_auto_ai.py")):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(("." * node.level) + (node.module or ""))
    assert imported == {"re", "dataclasses", "app.shared.llm", ".photo_rec_ai"}


def test_the_auto_prompt_takes_no_input_and_the_call_sends_only_the_photo(monkeypatch):
    import inspect

    assert not inspect.signature(auto_ai.prompt).parameters  # 가족·사용자 값을 받는 자리가 없다
    seen = {}

    def fake_complete_json(prompt, schema, **kwargs):
        seen.update(prompt=prompt, schema=schema, kwargs=kwargs)
        data = {
            "usable": False,
            "question": "",
            "options": [],
            "answer_index": 0,
            "box_x": 0.5,
            "box_y": 0.5,
        }
        return SimpleNamespace(data=data, input_tokens=1, output_tokens=1)

    monkeypatch.setattr(auto_ai.llm, "complete_json", fake_complete_json)
    jpeg = b"\xff\xd8public-photo"
    auto_ai.make_question(jpeg)
    assert seen["prompt"] == auto_ai.prompt() and seen["kwargs"]["images"] == [jpeg]
    assert seen["kwargs"]["system"] == auto_ai.SYSTEM
    assert set(seen["kwargs"]) == {"system", "max_tokens", "effort", "timeout", "images"}


def test_the_auto_path_is_reachable_only_through_one_argumentless_trigger():
    files = _app_files()
    # make_question·run_daily 는 자동 보충 모듈 안에서만 쓰인다
    callers = {rel for rel, text in files.items() if "make_question" in text}
    assert callers <= {"features/play/photo_rec_auto_ai.py", "features/play/photo_rec_auto.py"}
    router = _tree(PLAY / "router.py")
    triggers = [
        n
        for n in ast.walk(router)
        if isinstance(n, ast.Call) and _is(n.func, "photo_rec_auto.ensure_today_in_background")
    ]
    assert (
        len(triggers) == 1 and not triggers[0].args and not triggers[0].keywords
    )  # 요청 값을 넘기지 않는다
    assert [
        rel
        for rel, text in files.items()
        if "run_daily(" in text and rel != "features/play/photo_rec_auto.py"
    ] == []


def test_the_auto_path_is_off_by_default_and_bounded():
    fields = Settings.model_fields
    assert fields["photo_rec_auto_enabled"].default is False  # 켜는 것은 운영 환경변수뿐이다
    assert fields["photo_rec_auto_per_day"].default <= 5
    assert fields["photo_rec_auto_max_attempts"].default <= 3
    source = (PLAY / "photo_rec_auto.py").read_text(encoding="utf-8")
    assert "photo_rec_auto_enabled" in source and "photo_rec_auto_per_day" in source


# ---- Pixabay: 고정 검색어·키만, 호출자는 하나 ----------------------------------------------------------------------------------
def test_pixabay_client_has_one_app_caller_and_a_fixed_query_list():
    files = _app_files()
    users = {
        rel for rel, text in files.items() if "photo_rec_pixabay" in text or "PixabayClient" in text
    } - {"features/play/photo_rec_pixabay.py"}
    assert users == {"features/play/photo_rec_auto.py"}
    auto = files["features/play/photo_rec_auto.py"]
    assert "pix.QUERIES" in auto  # 검색어는 고정 목록에서만 뽑는다(사용자 입력·대화 내용이 아니다)
