"""자동 분류. 가리기가 끝난 결과(content.text)만 본다 — 원본 글자와 파일 이름은 쓰지 않는다.
처방전·신분증·통장·가족관계증명서는 모두 가린 상태, 그 밖의 문서는 주민등록번호만 가린 상태다(masking.py).

    가린 글자 ─▶ 글자 없음 ───────────────▶ "사진"(가족 공유) / 빈 문서(사람 확인)
              ─▶ 처방전 ─────────────────▶ 규칙 (어떤 모델에도 보내지 않음)
              ─▶ 빠른 규칙(낱말 2개 이상) ─▶ 고지서 · 영수증
              (신분증·여권·운전면허·통장·가족관계증명서는 모두 가린 뒤 아래로 보낸다)
              ─▶ 그 밖 ─┬ Jev 키 있음 ─▶ Jev: 종류 고르기(목록)·문서인지·분야·기한·주요 금액 고르기
                        │               ├ 목록에 없는 종류 ─▶ 로컬 언어 모델이 이름 붙임 + 사람 확인
                        │               └ 호출 실패 ─▶ 아래 로컬로
                        └ 키 없음 ───▶ 로컬 언어 모델(Ollama) ─▶ 자유 문구 종류·태그·날짜·금액·장소·폼 칸
                                       └ 꺼져 있거나 답이 깨짐 ─▶ "기타 문서" + 사람 확인

처방전·고지서·영수증은 규칙으로 정해 어떤 모델에도 보내지 않는다. Jev 에는 이 글자와 코드가 찾은
날짜·금액 후보만 보낸다(Jev 는 글을 만들지 않고 보기 중에서 고른다).
모델은 app/shared/llm 의 jev.py · local.py 로만 부른다.
"""

import re
from collections.abc import Callable

from app.shared.llm import jev as jev_api
from app.shared.llm import local
from app.shared.llm.client import LLMUnavailable

from . import masking
from .schemas import Amount, Classification, PreprocessResult

Llm = Callable[..., dict]  # (prompt, system=...) -> dict
Jev = Callable[[dict, dict], dict]  # (state, questions) -> answers

MAX_CHARS = 3000  # 모델에 넘기는 글자 수(앞부분이 종류를 가장 잘 말해 준다)
REVIEW_BELOW = 0.6
_RULES = (  # (종류, 낱말들) — 위에서부터 먼저 맞는 것
    ("고지서", ("고지서", "납기", "납부", "청구금액", "사용량", "관리비", "자동이체")),
    ("영수증", ("영수증", "합계", "승인번호", "카드", "부가세", "결제금액", "판매")),
)
_DATE = re.compile(r"(20\d{2})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})")
_MONEY = re.compile(r"([가-힣]{2,8})\s*[:：]?\s*(\d{1,3}(?:,\d{3})+|\d{4,})\s*원")
_AMOUNT = re.compile(
    r"(합\s*계|총\s*액|청구\s*금액|결제\s*금액|받을\s*금액|납부\s*금액)\s*[:：]?\s*(\d{1,3}(?:,\d{3})+|\d+)\s*원?"
)

# Jev 가 고르는 문서 종류. 목록에 없으면 "none" → 로컬 모델이 새 이름을 붙인다(목록은 늘려 간다)
DOC_TYPES = {
    "학교 가정통신문": "초·중·고등학교가 학부모에게 보내는 안내(현장체험학습, 방과후, 급식, 상담 등)",
    "학원 안내문": "학원·교습소의 수업·수강료·휴원 안내",
    "어린이집·유치원 알림장": "어린이집·유치원의 알림, 준비물, 행사 안내",
    "성적표·생활기록부": "시험 결과, 성적 통지, 생활기록부",
    "아파트 관리사무소 공지": "아파트·건물 관리사무소의 점검·공사·주차·생활 공지",
    "임대차·부동산 계약서": "전세·월세·매매 계약서, 확정일자, 부동산 서류",
    "보험 증권·안내문": "보험 가입 증권, 약관 요약, 갱신·만기 안내",
    "은행·카드사 안내문": "은행·카드사의 이용 안내, 혜택·약관 변경 안내",
    "세금·공공요금 안내": "국세·지방세 안내, 연말정산, 자동차세, 공공기관 납부 안내",
    "관공서 통지서": "주민센터·구청·법원·경찰 등에서 온 통지·안내",
    "건강검진 결과지": "건강검진·종합검진 결과",
    "병원 진료 안내": "진료 예약, 검사 안내, 입·퇴원 안내",
    "예방접종 안내": "아이·어른 예방접종 일정·안내",
    "택배·배송 안내": "택배 도착·배송 조회·반품 안내",
    "쇼핑 주문 내역": "온라인 쇼핑 주문 확인, 결제 완료 내역",
    "여행 일정표·예약 확인서": "여행 일정, 항공·숙소·기차 예약 확인",
    "행사·모임 초대장": "결혼식·돌잔치·동창회·가족 모임 초대",
    "가계부·지출 정리": "가족 수입·지출을 정리한 표",
    "제품 설명서·보증서": "가전·물건의 사용 설명서, 품질 보증서",
    "레시피": "요리 재료와 만드는 방법",
    "일상 메모": "가족끼리 주고받은 짧은 메모·쪽지·문자",
    "업무 문서": "회사 일과 관련된 보고서·회의록·발표 자료",
    "주민등록증": "주민등록증 앞면·뒷면",
    "운전면허증": "자동차 운전면허증",
    "여권": "여권 정보면",
    "외국인등록증": "외국인등록증, 영주증",
    "통장 사본": "은행 통장 앞면·사본, 계좌 정보",
    "가족관계증명서": "가족관계증명서, 가족관계등록부 증명서",
    "none": "위 어디에도 맞지 않는 다른 종류",
}
DOMAINS = {
    "학교·교육": "학교, 학원, 어린이집, 공부",
    "의료·건강": "병원, 약, 검진, 접종",
    "주거·관리": "집, 아파트, 관리비, 이사",
    "금융·보험": "은행, 카드, 보험, 세금",
    "쇼핑·생활": "구매, 배송, 생활용품, 요리",
    "여행·행사": "여행, 나들이, 모임, 경조사",
    "행정·공공": "관공서, 증명서, 공공 안내",
    "가족 일상": "가족 대화, 메모, 일상 기록",
    "기타": "위 어디에도 아님",
}
POLICY = (
    "가족 비서 앱이 가족이 올린 파일의 글자를 읽고 종류를 정한다. "
    "글자는 개인정보를 가린 상태다(*, [주소 가림] 같은 표시)."
)

SYSTEM = (
    "너는 가족 비서 앱의 문서 분류기다. 글자는 개인정보를 가린 상태다(*, [주소 가림] 같은 표시). "
    "가린 부분을 추측하거나 되살리지 마라. 글자에 없는 내용을 지어내지 마라. JSON 객체 하나로만 답한다."
)
PROMPT = """아래 글자를 읽고 이 JSON 으로 답해.
{{
  "doc_type": "보낸 곳과 문서 종류가 드러나는 짧은 이름. '안내문'처럼 뭉뚱그리지 말 것 (예: 학교 가정통신문, 아파트 관리사무소 공지, 아파트 관리비 고지서, 보험 증권, 가계부, 여행 계획표)",
  "is_document": true 또는 false (안내문·고지서·계약서·표처럼 챙겨야 할 문서면 true, 일상 메모·사진 속 간판이면 false),
  "tags": ["검색용 낱말 5개 이하"],
  "dates": ["YYYY-MM-DD"],
  "amounts": [{{"label": "무슨 돈", "value": 숫자}}],
  "places": ["장소 이름"],
  "fields": {{"제출 기한": "YYYY-MM-DD" 처럼 이 종류에 중요한 칸}},
  "confidence": 0~1
}}

글자:
{text}"""


def classify(
    result: PreprocessResult, llm: Llm | None = None, jev: Jev | None = None
) -> Classification | None:
    """jev 를 주지 않으면 TYPESAFE_API_KEY 가 있을 때 Jev, 없으면 로컬 언어 모델로 정한다."""
    if result.quality.status == "failed":
        return None
    text = result.content.text.strip()
    if not text:
        if result.source.kind == "image":
            return Classification(doc_type="사진", route="daily_share", confidence=0.9, by="rule")
        return _review("빈 문서")
    if result.privacy.sensitive == "prescription":
        return _by_rule("처방전", 0.9, text)
    flat = re.sub(r"\s+", "", text)
    for doc_type, words in _RULES:
        hits = sum(w in flat for w in words)
        if hits >= 2:
            return _by_rule(doc_type, 0.9 if hits >= 3 else 0.75, text)
    text, llm = text[:MAX_CHARS], llm or local.complete_json
    if jev is None and jev_api.available():
        jev = jev_api.ask
    if jev is not None:
        return _by_jev(text, jev, llm)
    return _by_model(text, llm)


def _by_jev(text: str, jev: Jev, llm: Llm) -> Classification:
    dates = _dates(text)
    money = _money(text)
    money_keys = [f"{a.label} {a.value:,}원" for a in money]
    questions = {
        "doc_type": {
            "type": "choice",
            "instructions": "`text` 는 가족이 올린 파일의 글자다. 이 파일은 어떤 종류의 문서인가?",
            "criteria": DOC_TYPES,
        },
        "is_document": {
            "type": "noul",
            "instructions": "`text` 는 날짜·돈·할 일을 챙겨야 하는 문서인가?",
            "criteria": {
                "true": "안내문·통지서·계약서·표·예약 확인처럼 나중에 다시 찾아보거나 챙길 문서",
                "false": "가족끼리의 짧은 메모·잡담·사진 속 간판처럼 일상 공유 글",
            },
        },
        "domain": {
            "type": "choice",
            "instructions": "`text` 는 가족 생활의 어느 분야에 속하는가?",
            "criteria": DOMAINS,
        },
    }
    if dates:
        questions["deadline"] = {
            "type": "choice",
            "instructions": (
                "`text` 에서 가족이 무언가를 내거나 신청하거나 돈을 내야 하는 마감 날짜는 "
                "`date_candidates` 중 무엇인가?"
            ),
            "criteria": {d: f"{d} 가 제출·신청·납부 마감일" for d in dates}
            | {"없음": "마감 날짜가 없음(행사일·발행일만 있음)"},
        }
    if money:
        questions["main_amount"] = {
            "type": "choice",
            "instructions": (
                "`text` 에서 가족이 내거나 받아야 하는 가장 중요한 금액은 "
                "`amount_candidates` 중 무엇인가?"
            ),
            "criteria": {k: f"{k} 를 내거나 받음" for k in money_keys}
            | {"없음": "챙길 금액이 없음"},
        }
    state = {
        "app": POLICY,
        "text": text,
        "date_candidates": dates,
        "amount_candidates": money_keys,
    }
    try:
        ans = jev(state, questions)
        pick = ans["doc_type"]
        doc_type, confidence = str(pick["choice"]), float(pick["confidence"])
        is_document = float(ans["is_document"]["noul"])
        domain = str(ans["domain"]["choice"])
    except (LLMUnavailable, KeyError, TypeError, ValueError):
        return _by_model(text, llm)  # Jev 가 안 되면 로컬로
    if doc_type not in DOC_TYPES or doc_type == "none":
        named = _by_model(text, llm)  # 처음 보는 종류: 이름은 로컬 모델이 붙이고 사람이 확인
        return named.model_copy(update={"needs_review": True, "route": "review"})
    needs_review = confidence < REVIEW_BELOW
    route = "review" if needs_review else ("document" if is_document >= 0.5 else "daily_share")
    fields = {}
    deadline = _picked(ans.get("deadline"))
    if deadline in dates:
        fields["기한"] = deadline
    main = _picked(ans.get("main_amount"))
    if main in money_keys:
        fields["주요 금액"] = main
        money.insert(0, money.pop(money_keys.index(main)))
    return Classification(
        doc_type=doc_type,
        route=route,
        confidence=round(confidence, 3),
        needs_review=needs_review,
        by="jev",
        tags=[doc_type] + ([domain] if domain in DOMAINS and domain != "기타" else []),
        dates=dates,
        amounts=money,
        fields=fields,
    )


def _picked(answer) -> str | None:
    """choice 답에서 '없음' 이 아니고 충분히 확실한 고른 값."""
    if not isinstance(answer, dict) or answer.get("choice") in (None, "없음"):
        return None
    try:
        return str(answer["choice"]) if float(answer.get("confidence", 0)) >= 0.5 else None
    except (TypeError, ValueError):
        return None


def _by_rule(doc_type: str, confidence: float, text: str) -> Classification:
    return Classification(
        doc_type=doc_type,
        route="document",
        confidence=confidence,
        by="rule",
        tags=[doc_type],
        dates=_dates(text),
        amounts=_amounts(text),
    )


def _by_model(text: str, llm: Llm) -> Classification:
    try:
        raw = llm(PROMPT.format(text=text), system=SYSTEM)
    except LLMUnavailable:
        return _review("기타 문서")
    doc_type = _clean(raw.get("doc_type"), 30)
    if not doc_type:
        return _review("기타 문서")
    try:
        confidence = min(max(float(raw.get("confidence", 0)), 0.0), 1.0)
    except (TypeError, ValueError):
        confidence = 0.0
    needs_review = confidence < REVIEW_BELOW
    if needs_review:
        route = "review"
    else:
        route = "daily_share" if raw.get("is_document") is False else "document"
    fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}
    return Classification(
        doc_type=doc_type,
        route=route,
        confidence=round(confidence, 3),
        needs_review=needs_review,
        by="model",
        tags=_strings(raw.get("tags"), 5, 20),
        dates=[d for d in (_date(x) for x in _list(raw.get("dates"))) if d][:10],
        amounts=_model_amounts(raw.get("amounts")),
        places=_strings(raw.get("places"), 5, 40),
        fields={
            k: v for k, v in ((_clean(k, 20), _clean(v, 100)) for k, v in fields.items()) if k and v
        },
    )


def _review(doc_type: str) -> Classification:
    return Classification(doc_type=doc_type, route="review", needs_review=True)


def _clean(value, limit: int) -> str:
    """모델 답도 한 번 더 가린다 — 혹시 주민등록번호 꼴을 지어내도 결과에 남지 않게."""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return ""
    return masking.mask_text(str(value).strip())[:limit]


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _strings(value, count: int, limit: int) -> list[str]:
    out = []
    for item in _list(value):
        s = _clean(item, limit)
        if s and s not in out:
            out.append(s)
    return out[:count]


def _date(value) -> str | None:
    m = _DATE.search(str(value))
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{y:04d}-{mo:02d}-{d:02d}" if 1 <= mo <= 12 and 1 <= d <= 31 else None


def _dates(text: str) -> list[str]:
    out = []
    for m in _DATE.finditer(text):
        d = _date(m.group(0))
        if d and d not in out:
            out.append(d)
    return out[:10]


def _amounts(text: str) -> list[Amount]:
    return [
        Amount(label=re.sub(r"\s+", "", m.group(1)), value=int(m.group(2).replace(",", "")))
        for m in _AMOUNT.finditer(text)
    ][:10]


def _money(text: str) -> list[Amount]:
    """'버스비 12,000원' 처럼 이름 붙은 금액 후보(같은 것은 한 번)."""
    out = []
    for m in _MONEY.finditer(text):
        a = Amount(label=m.group(1), value=int(m.group(2).replace(",", "")))
        if a not in out:
            out.append(a)
    return out[:10]


def _model_amounts(value) -> list[Amount]:
    out = []
    for item in _list(value):
        if not isinstance(item, dict):
            continue
        try:
            n = int(str(item.get("value", "")).replace(",", "").replace("원", "").strip())
        except ValueError:
            continue
        out.append(Amount(label=_clean(item.get("label", ""), 30), value=n))
    return out[:10]
