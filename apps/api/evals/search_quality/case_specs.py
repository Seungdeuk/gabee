"""검색 품질 24개 사례 선언(모델 출력·검색 결과를 보기 전에 고정). `cases.json` 은 이 선언에서 만든다(`build`).

사례 한 건의 필드
- `queries`: 검색어 묶음. `ideal`(질문에서 사람이 고를 가장 좋은 키워드), `naive`(질문 문장의 낱말을 그대로 쓴 검색어),
  `agent`(에이전트가 만든 검색어 슬롯, 이번 단계에서는 비어 있다). q23 은 `history` 가 있는 `ideal` 과, history 없이 쓰는 진단 묶음 `no_history` 를 둔다.
  검색어는 공백으로 나뉜 낱말 목록이고 모든 낱말이 들어 있는 글만 나온다(운영 검색과 같다).
- `gold`: 질문의 정답 근거가 담긴 메시지 키. `acceptable`: 같은 주제의 맥락 글(나와도 위반은 아니지만 정답으로 세지 않는다).
  `forbidden`: 나오면 안 되는 글(다른 가족·1:1·삭제글 미끼).
- `key_facts`: 정답 글(또는 카드 주석)에 반드시 들어 있어야 하는 핵심 사실 문자열. 없으면 평가를 중단한다.
- `state`: 시점·결정 상태(confirmed | changed | cancelled | undecided | none). 답변 평가(Judge)가 쓴다.
- `expected_cause`: 묶음별로 미리 정한 미검출 원인(없으면 정상 검색). 값은 `attribution.CAUSES`. 실제 원인이 다르면 회귀 시험이 실패한다.
- `lexical_gap`: 질문의 개념어가 gold 글에 없는 동의어·간접 표현 사례(키워드 검색의 한계). `card`: 내용이 text 에 색인되지 않는 카드 사례.
- `known_limitation`: 이 사례가 기존 구현의 알려진 한계인가. 하위집단 지표를 따로 내려고만 쓰고, 품질 평균에서 빼지 않는다.
"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES_PATH = HERE / "cases.json"
PINS_PATH = HERE / "cases.pins.json"

# 사례 변경 이력(코드 상수). 출력(검색 결과)을 본 뒤에는 사례를 바꾸지 않는다. 바꾸면 여기에 이유와 전후 해시를 남긴다.
HISTORY: list[dict] = []


def _c(
    cid,
    category,
    question,
    ideal,
    naive,
    gold,
    facts,
    *,
    acceptable=(),
    forbidden=(),
    state="none",
    expected=None,
    naive_expected="query_selection",
    lexical_gap=False,
    card=False,
    known=False,
    history=None,
    extra_queries=None,
):
    queries = {"ideal": ideal.split(), "naive": naive.split(), "agent": []}
    causes = {"ideal": "", "naive": "" if not gold else naive_expected, "agent": ""}
    if expected is not None:
        causes["ideal"] = expected
    if extra_queries:
        for name, (words, cause) in extra_queries.items():
            queries[name] = words.split()
            causes[name] = cause
    return {
        "id": cid,
        "category": category,
        "question": question,
        "history": history,
        "queries": queries,
        "gold": list(gold),
        "acceptable": list(acceptable),
        "forbidden": list(forbidden),
        "key_facts": list(facts),
        "state": state,
        "expected_cause": causes,
        "lexical_gap": lexical_gap,
        "card": card,
        "known_limitation": known,
    }


KEEP = "keyword_limitation"
SPECS: list[dict] = [
    # 정확한 단어(3)
    _c(
        "q01",
        "exact",
        "치과 예약 언제였지?",
        "치과",
        "치과 예약 언제",
        ["m01"],
        ["목요일", "오후 3시"],
        acceptable=["m02"],
        state="confirmed",
    ),
    _c(
        "q02",
        "exact",
        "이삿짐센터 견적 얘기 어떻게 됐어?",
        "이삿짐센터",
        "이삿짐센터 견적 얘기",
        ["m03"],
        ["푸른이사", "180만 원"],
        acceptable=["m04"],
        state="confirmed",
    ),
    _c(
        "q03",
        "exact",
        "제주 항공권 어떻게 됐어?",
        "제주 항공권",
        "제주 항공권 어떻게 됐어",
        ["m05"],
        ["12월 20일", "23일"],
        state="confirmed",
    ),
    # 여러 검색어(3)
    _c(
        "q04",
        "multi_keyword",
        "할머니 생신 식당 어디로 했지?",
        "할머니 생신 식당",
        "할머니 생신 장소",
        ["m06"],
        ["한강 한정식", "토요일 12시"],
        acceptable=["m07"],
        state="confirmed",
    ),
    _c(
        "q05",
        "multi_keyword",
        "하준 학원 시간 바뀐 거 뭐였지?",
        "학원 시간",
        "학원 시간 바뀐",
        ["m08"],
        ["수요일 6시"],
        acceptable=["m09"],
        state="changed",
    ),
    _c(
        "q06",
        "multi_keyword",
        "캠핑 준비물 뭐였지?",
        "캠핑 준비물",
        "캠핑 준비물 뭐",
        ["m10"],
        ["텐트", "침낭"],
        acceptable=["m11"],
        state="confirmed",
    ),
    # 동의어·간접 표현(3): 기존 키워드 검색의 한계
    _c(
        "q07",
        "synonym",
        "병원 얘기 한 적 있어?",
        "병원",
        "병원 얘기",
        ["m12", "m01"],
        ["내과"],
        expected=KEEP,
        naive_expected=KEEP,
        lexical_gap=True,
        known=True,
        state="confirmed",
    ),
    _c(
        "q08",
        "synonym",
        "차 정비 언제 하기로 했지?",
        "차 정비",
        "차 정비 언제",
        ["m13"],
        ["월요일 오전"],
        expected=KEEP,
        naive_expected=KEEP,
        lexical_gap=True,
        known=True,
        state="confirmed",
    ),
    _c(
        "q09",
        "synonym",
        "저녁 같이 먹자는 얘기 나왔어?",
        "저녁 먹자",
        "저녁 같이 먹자",
        ["m14"],
        ["토요일", "6시"],
        expected=KEEP,
        naive_expected=KEEP,
        lexical_gap=True,
        known=True,
        state="undecided",
    ),
    # 오래된 글과 최신 글(2)
    _c(
        "q10",
        "recency",
        "제일 최근에 정한 대청소 날짜가 언제야?",
        "대청소",
        "대청소 날짜",
        ["m17"],
        ["11월 15일", "9시"],
        acceptable=["m15", "m16"],
        state="changed",
    ),
    _c(
        "q11",
        "recency",
        "처음에 정했던 가족 모임 날짜가 언제였지?",
        "가족 모임",
        "처음 정한 모임 날짜",
        ["m18"],
        ["10월 3일"],
        acceptable=["m19", "m20"],
        expected="result_limit",
        state="changed",
    ),
    # 확정 후 변경·취소(3)
    _c(
        "q12",
        "change",
        "토요일 집들이 시간 최종으로 몇 시야?",
        "집들이",
        "토요일 약속 확정",
        ["m22", "m23"],
        ["6시", "확인"],
        acceptable=["m21", "m25"],
        state="changed",
    ),
    _c(
        "q13",
        "cancel",
        "외식 취소됐어?",
        "외식",
        "외식 취소됐어",
        ["m25"],
        ["취소"],
        acceptable=["m14", "m24"],
        state="cancelled",
    ),
    _c(
        "q14",
        "change",
        "영화 시간 최종은?",
        "영화",
        "영화 시간 최종",
        ["m28"],
        ["4시 30분", "확정"],
        acceptable=["m26", "m27"],
        state="changed",
    ),
    # 아직 결정되지 않은 이야기(2)
    _c(
        "q15",
        "undecided",
        "겨울 여행지 정해졌어?",
        "여행",
        "여행지 정해졌어",
        ["m29", "m31"],
        ["부산", "강릉", "더 생각"],
        acceptable=["m30"],
        state="undecided",
    ),
    _c(
        "q16",
        "undecided",
        "부모님 선물 뭐로 하기로 했어?",
        "부모님 선물",
        "부모님 선물 뭐로",
        ["m32"],
        ["안마기", "건강검진권"],
        acceptable=["m33"],
        state="undecided",
    ),
    # 결과 없음(2)
    _c(
        "q17", "no_result", "수영장 얘기 한 적 있어?", "수영장", "수영장 얘기", [], [], state="none"
    ),
    _c(
        "q18",
        "no_result",
        "계약금 얼마 냈는지 얘기했어?",
        "계약금",
        "계약금 얼마",
        [],
        [],
        state="none",
    ),
    # 삭제된 메시지(1)
    _c(
        "q19",
        "deleted",
        "가족 사진 촬영 장소 어디로 했지?",
        "광교",
        "광교 호수공원",
        [],
        [],
        forbidden=["m34", "m35"],
        state="none",
    ),
    # 접근 제한(3)
    _c(
        "q20",
        "other_family",
        "이웃집은 이번 주말 어디 캠핑 간대?",
        "가평",
        "가평 캠핑장",
        [],
        [],
        forbidden=["o01"],
        state="none",
    ),
    _c(
        "q21",
        "direct_room",
        "수진이랑 지민이 1:1로 하준 생일 준비 얘기했어?",
        "깜짝파티",
        "깜짝파티 준비",
        [],
        [],
        forbidden=["d01"],
        state="none",
    ),
    _c(
        "q22",
        "direct_room",
        "하준이랑 수진이가 성적표 얘기했어?",
        "성적표",
        "성적표 얘기",
        [],
        [],
        forbidden=["d03"],
        state="none",
    ),
    # 문맥을 알아야 하는 질문(2)
    _c(
        "q23",
        "context",
        "그거 언제 얘기했지?",
        "이삿짐센터",
        "이삿짐센터 견적",
        ["m03"],
        ["푸른이사"],
        state="confirmed",
        history=[
            {"role": "user", "text": "우리 이삿짐센터 견적 알아봤었지?"},
            {"role": "assistant", "text": "네, 이삿짐센터 견적 얘기가 있었어요."},
        ],
        extra_queries={"no_history": ("그거", "context_needed")},
        naive_expected="",
    ),
    _c(
        "q24",
        "card",
        "수진이 공유한 일정 내용이 뭐였지?",
        "치과 검진",
        "공유한 일정",
        ["m36"],
        ["11월 12일", "오후 4시"],
        expected="content_not_indexed",
        naive_expected="content_not_indexed",
        card=True,
        known=True,
        state="confirmed",
    ),
]


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def build() -> list[dict]:
    return json.loads(json.dumps(SPECS, ensure_ascii=False))


def world_sha() -> str:
    from . import data

    rows = [[m.key, m.room, m.author, m.day, m.text, m.deleted, m.card] for m in data.ordered()]
    return sha(rows)


def build_pins() -> dict:
    rows = build()
    return {
        "frozen": True,
        "case_count": len(rows),
        "ids": [r["id"] for r in rows],
        "case_sha256": {r["id"]: sha(r) for r in rows},
        "cases_sha256": sha(rows),
        "world_sha256": world_sha(),
        "history": HISTORY,
    }


def write() -> None:
    rows = build()
    CASES_PATH.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    PINS_PATH.write_text(
        json.dumps(build_pins(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def load() -> list[dict]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def check_pins() -> list[str]:
    """파일·핀·선언이 서로 일치하는지 검사한다. 어긋난 항목의 설명 목록(비어 있으면 일치)."""
    problems: list[str] = []
    try:
        cases = load()
        pins = json.loads(PINS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"사례·핀 파일을 읽을 수 없다: {e}"]
    if cases != build():
        problems.append("cases.json 이 선언(SPECS)과 다르다")
    expected = build_pins()
    for key in (
        "frozen",
        "case_count",
        "ids",
        "case_sha256",
        "cases_sha256",
        "world_sha256",
        "history",
    ):
        if pins.get(key) != expected[key]:
            problems.append(f"핀 불일치: {key}")
    return problems


if __name__ == "__main__":
    write()
