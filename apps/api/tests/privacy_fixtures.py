"""개인정보 가명화 시험용 가짜 데이터 세트(전부 가상이다. 실제 사람·번호·주소·계좌가 아니다).

- 가족 구성원 5명: 성이 같은 두 명(박지훈/박지후: 한 글자 차이), 낱말과 겹치는 이름(이하늘, 한가을, 강바다), 표시 이름 포함
- 기록 28개: 영수증·병원·학교·임대차·보험·학원·택배·메모 등. 본문에 이름·전화(여러 표기)·주소·이메일·계좌를 심었다
- 전화번호는 실제로 있을 수 없는 모양(5550-01xx)만 쓴다. 이메일은 example.* 도메인이다.

`PLANTED` 는 "심은 값" 표다. 시험이 모델로 간 요청 본문에서 이 값이 보이는지(= 샌 것) 센다.
`KNOWN_MISSES` 는 탐지기가 원래 놓치는 값이라 따로 모았다(통과시키지 않고 xfail 표로 남긴다)."""

import re
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

from sqlalchemy import select

from app.features.ai_assistant.knowledge import service
from app.features.family_group.models import User
from app.shared.db import SessionLocal
from tests.helpers import join_family, signup

# (실명, 표시 이름). 박지훈/박지후는 성이 같고 한 글자만 다르다. 하늘·가을·바다는 흔한 낱말이기도 하다.
MEMBERS = [
    ("박지훈", "훈이"),
    ("박지후", None),
    ("이하늘", "하늘이"),
    ("한가을", "가을이"),
    ("강바다", "바다"),
]

# 기록 하나 = (분류, 제목, 본문, 날짜)
RECORDS: list[tuple[str, str, str, date]] = [
    (
        "영수증",
        "동네마트 영수증 10월",
        "# 동네마트 영수증\n분류: 영수증\n- 구매자 박지훈 (회원 010-5550-0101)\n- 합계 48,200원\n- 결제 카드 4111-1111-1111-1111\n- 영수증 번호 20261003-0042",
        date(2026, 10, 3),
    ),
    (
        "병원 진료 내역서",
        "박지후 소아과 진료",
        "# 소아과 진료 내역서\n분류: 병원 진료 내역서\n- 환자 박지후 (보호자 박지훈)\n- 보호자 연락처 010 5550 0102\n- 진료비 12,000원\n- 병원 주소 서울특별시 마포구 다람쥐로 77, 3층",
        date(2026, 9, 20),
    ),
    (
        "병원 안내문",
        "치과 예약 안내",
        "# 치과 예약 안내\n분류: 병원 안내문\n- 예약자 이하늘님\n- 예약 문의 02-5550-0107\n- 11월 5일 오후 3시\n- 이메일 확인 메일은 haneul.lee.fake@example.org 로 갑니다",
        date(2026, 10, 28),
    ),
    (
        "학교 가정통신문",
        "3학년 가을 현장학습 가정통신문",
        "# 가정통신문\n분류: 학교 가정통신문\n- 학생 박지후\n- 담임 상담 연락처 010.5550.0103\n- 학부모 이하늘님께 참가 동의서를 받습니다\n- 준비물 도시락, 물",
        date(2026, 10, 12),
    ),
    (
        "임대차 계약서",
        "아파트 임대차 계약서",
        "# 임대차 계약서\n분류: 임대차 계약서\n- 임차인 박지훈\n- 임대 주소 서울특별시 마포구 다람쥐로 77, 101동 1202호\n- 임대료 입금 계좌 농협 110-555-012345\n- 임대인 윤재석 씨 연락처 010-5550-0109\n- 보증금 2억원",
        date(2026, 3, 1),
    ),
    (
        "보험 증권",
        "실손 보험 증권",
        "# 보험 증권\n분류: 보험 증권\n- 피보험자 박지훈\n- 보험료 자동이체 계좌 우리 1002-555-678901\n- 안내 이메일 jihun.park.fake@example.com\n- 월 보험료 64,300원",
        date(2026, 1, 15),
    ),
    (
        "학원 안내",
        "영어학원 11월 안내",
        "# 영어학원 안내\n분류: 학원 안내\n- 수강생 한가을\n- 학부모 연락처 01055500104\n- 학원 위치 경기도 성남시 분당구 은행나무길 15-3\n- 수강료 280,000원",
        date(2026, 10, 30),
    ),
    (
        "택배 알림",
        "택배 도착 안내",
        "# 택배 도착 안내\n분류: 택배 알림\n- 받는 분 강바다\n- 연락처 010-5550-0105\n- 배송지 서울 강남구 소나무로 152번길 9, 3층 301호\n- 운송장 번호 1234567890123",
        date(2026, 10, 25),
    ),
    (
        "메모",
        "일상 메모 (학원 데리러 가기)",
        "# 일상 메모\n분류: 메모\n- 지훈이 학원 끝나면 6시에 데리러 가기\n- 지후는 토요일 수영\n- 훈이 아빠 생일은 3월 14일\n- 맑은 하늘 아래 가을 소풍 도시락 싸기",
        date(2026, 10, 14),
    ),
    (
        "관리비 고지서",
        "10월 아파트 관리비",
        "# 관리비 고지서\n분류: 관리비 고지서\n- 입주자 이하늘\n- 동호수 101동 1202호\n- 관리비 187,400원\n- 문의 +82 10-5550-0106",
        date(2026, 10, 31),
    ),
    (
        "전기요금 고지서",
        "10월 전기요금",
        "# 전기요금 고지서\n분류: 전기요금 고지서\n- 명의 박지훈\n- 사용량 312 kWh\n- 청구금액 48,200원\n- 납기일 2026-11-25",
        date(2026, 10, 1),
    ),
    (
        "통신요금 고지서",
        "휴대폰 요금 명세서",
        "# 통신요금 명세서\n분류: 통신요금 고지서\n- 가입자 박지훈 (010-5550-0101)\n- 청구서 메일 jihun.park.fake@example.com\n- 청구금액 58,000원",
        date(2026, 10, 5),
    ),
    (
        "수도요금 고지서",
        "10월 상하수도 요금",
        "# 상하수도 요금\n분류: 수도요금 고지서\n- 사용량 18톤\n- 요금 23,400원\n- 명의 이하늘 (101동 1202호)",
        date(2026, 10, 3),
    ),
    (
        "영수증",
        "학교 급식비 영수증",
        "# 급식비 영수증\n분류: 영수증\n- 학생 박지후\n- 급식비 63,000원\n- 입금자 박지훈",
        date(2026, 10, 7),
    ),
    (
        "약국 처방전",
        "한가을 감기약 처방전",
        "# 처방전\n분류: 약국 처방전\n- 환자 한가을 (주민번호 900101-2345678)\n- 감기약 3일분\n- 약국 문의 010-5550-0108",
        date(2026, 10, 18),
    ),
    (
        "건강검진 결과",
        "이하늘 건강검진 결과",
        "# 건강검진 결과\n분류: 건강검진 결과\n- 수검자 이하늘\n- 결과 안내 메일 haneul.lee.fake@example.org\n- 혈압 정상\n- 재검 필요 없음",
        date(2026, 6, 2),
    ),
    (
        "항공권",
        "제주 항공권 예약 확인",
        "# 항공권 예약\n분류: 항공권\n- 탑승객 박지훈, 박지후\n- 영문 표기 PARK JIHUN\n- 예약자 연락처 010-5550-0101\n- 결제 금액 182,000원",
        date(2026, 7, 20),
    ),
    (
        "자동차 보험",
        "자동차 보험 갱신 안내",
        "# 자동차 보험 갱신\n분류: 자동차 보험\n- 계약자 박지훈\n- 이체 계좌 3333-05-1234567\n- 보험료 612,000원",
        date(2026, 5, 2),
    ),
    (
        "학원비 영수증",
        "수학학원 학원비 영수증",
        "# 학원비 영수증\n분류: 학원비 영수증\n- 수강생 박지후 (형 박지훈)\n- 학원비 310,000원\n- 입금 확인 문자는 010-5550-0101 로 보냅니다",
        date(2026, 9, 3),
    ),
    (
        "가족 모임",
        "가족 모임 장소 안내",
        "# 가족 모임\n분류: 가족 모임\n- 장소 서울특별시 마포구 다람쥐로 77\n- 참석 박지훈, 이하늘, 한가을, 강바다\n- 시간 12월 24일 저녁 6시",
        date(2026, 12, 24),
    ),
    (
        "세금 안내",
        "종합소득세 환급 안내",
        "# 환급 안내\n분류: 세금 안내\n- 환급 대상 박지훈\n- 환급 계좌 우리 1002-555-678901\n- 환급액 83,000원",
        date(2026, 5, 20),
    ),
    (
        "도서관 안내",
        "도서관 대출 안내",
        "# 도서관 대출 안내\n분류: 도서관 안내\n- 회원 강바다\n- 반납일 11월 9일\n- 연락처 010-5550-0105",
        date(2026, 10, 26),
    ),
    (
        "병원 안내문",
        "동물병원 예방접종 안내",
        "# 동물병원 안내\n분류: 병원 안내문\n- 보호자 이하늘\n- 연락처 010 - 5550 - 0110\n- 주소 경기도 성남시 분당구 은행나무길 15-3",
        date(2026, 10, 21),
    ),
    (
        "카드 명세서",
        "신용카드 이용 명세서",
        "# 카드 이용 명세서\n분류: 카드 명세서\n- 카드 소유자 박지훈\n- 이용 금액 412,300원\n- 문의 메일 gaeul-han@example.net",
        date(2026, 10, 15),
    ),
    (
        "중고거래 메모",
        "중고 책상 거래 메모",
        "# 중고 거래\n분류: 중고거래 메모\n- 판매자 윤재석 씨\n- 연락처 010-5550-0109\n- 가격 45,000원\n- 박지훈이 토요일에 가지러 감",
        date(2026, 10, 22),
    ),
    (
        "학교 가정통신문",
        "운동회 안내 가정통신문",
        "# 운동회 안내\n분류: 학교 가정통신문\n- 학생 박지후\n- 응원 오시는 분 박지훈, 이하늘\n- 11월 2일 오전 10시",
        date(2026, 10, 29),
    ),
    (
        "영수증",
        "문구점 영수증",
        "# 문구점 영수증\n분류: 영수증\n- 구매 공책 5권\n- 합계 7,500원\n- 현금영수증 번호 010-5550-0101",
        date(2026, 10, 9),
    ),
    (
        "메모",
        "집 주소 메모",
        "# 집 주소 메모\n분류: 메모\n- 우리 집 서울특별시 마포구 다람쥐로 77, 101동 1202호\n- 택배는 경비실에 맡겨 달라고 하기\n- 강바다 외할머니 댁 서울 강남구 소나무로 152번길 9, 3층 301호",
        date(2026, 10, 11),
    ),
]

# 슬라이드 모양 기록(`## 제목` 구역). 구역 제목이 검색 결과의 page 칸으로 가는데 page 는 가리지 않는 키라서 새는지 보는 용도다.
# 일반 기록 세트에는 넣지 않는다(넣으면 일반 시험이 이 구멍 때문에 실패한다).
SLIDE_RECORD = (
    "가족 여행 계획",
    "제주 가족 여행 계획",
    "# 제주 가족 여행 계획\n분류: 가족 여행 계획\n## 박지훈 이하늘 제주 일정 010-5550-0101\n- 12월 24일 출발\n- 렌터카 예약\n## 숙소\n- 한가을 명의 예약",
    date(2026, 12, 1),
)

# 탐지기가 원래 놓치는 표기들(docs/security/PII_EVALUATION.md, detectors.py 한계). 기록에는 넣지 않고 질문·앞 대화에 직접 쓴다.
KNOWN_MISSES = {
    "phone_8digits_without_010": ("전화(010 없는 8자리)", "phone", "5550-0111"),
    "phone_hangul_digits": ("전화(한글 숫자)", "phone", "공일공 오오오공 공일일이"),
    "phone_spaced_digits": ("전화(숫자 사이 공백)", "phone", "0 1 0 5 5 5 0 0 1 1 3"),
    "name_unknown_without_honorific": ("낯선 이름(호칭 없음)", "other", "윤재석"),
    "name_nickname": ("별명", "other", "꼬북이"),
    "name_english": ("영문 이름", "other", "PARK JIHUN"),
    "address_building_name": ("건물 이름 약식 주소", "address", "강남역 3번 출구 앞 빌라"),
}


@dataclass(frozen=True)
class Planted:
    kind: str  # name | phone | address | email | account | other
    value: str  # 기록에 쓴 글자
    key: str  # 모델 요청에서 이 글자를 찾을 때 쓰는 값(전화·계좌는 숫자만 남긴 뒤 비교)
    bug: str | None = (
        None  # 탐지기의 알려진 구멍으로 확인된 값(일반 시험은 이 값을 빼고 따로 xfail 시험을 둔다)
    )


def _p(kind: str, value: str, key: str | None = None, bug: str | None = None) -> Planted:
    return Planted(kind, value, key or value, bug)


# 심은 값. 이름은 실명·표시 이름·이름만 쓴 꼴까지, 주소는 도로명+번호와 동호수를 따로 센다.
PLANTED: list[Planted] = [
    *[_p("name", v) for v in ("박지훈", "박지후", "이하늘", "한가을", "강바다")],
    *[_p("name", v) for v in ("훈이", "하늘이", "가을이", "바다", "지훈", "지후")],
    _p("phone", "010-5550-0101", "55500101"),
    _p("phone", "010 5550 0102", "55500102"),
    _p("phone", "010.5550.0103", "55500103"),
    _p("phone", "01055500104", "55500104"),
    _p("phone", "010-5550-0105", "55500105"),
    _p("phone", "+82 10-5550-0106", "55500106"),
    _p("phone", "02-5550-0107", "55500107"),
    _p("phone", "010-5550-0108", "55500108"),
    _p("phone", "010-5550-0109", "55500109"),
    _p("phone", "010 - 5550 - 0110", "55500110"),
    _p("address", "다람쥐로 77"),
    _p("address", "101동 1202호"),
    _p("address", "은행나무길 15-3"),
    _p("address", "소나무로 152번길 9"),
    _p("address", "301호", bug="3층 301호 처럼 층 뒤에 오는 호수는 가려지지 않는다"),
    _p("email", "jihun.park.fake@example.com"),
    _p("email", "haneul.lee.fake@example.org"),
    _p("email", "gaeul-han@example.net"),
    _p("account", "110-555-012345", "110555012345"),
    _p("account", "1002-555-678901", "1002555678901"),
    _p("account", "3333-05-1234567", "3333051234567"),
    _p("other", "900101-2345678", "9001012345678"),
    _p("other", "4111-1111-1111-1111", "4111111111111111"),
    _p("other", "윤재석"),
    _p("other", "PARK JIHUN"),
]

KINDS = ("name", "phone", "address", "email", "account", "other")
_NORMALIZE_KINDS = ("phone", "account", "other")


def _squash(text: str) -> str:
    return re.sub(r"[\s\-.]", "", text)


def leaked(planted: Planted, text: str) -> bool:
    """모델로 간 글에 심은 값이 그대로(전화·계좌는 구분 기호만 달라도) 보이는가."""
    if planted.kind in _NORMALIZE_KINDS:
        return planted.key in _squash(text)
    return planted.key in text


def planted_in_records() -> list[Planted]:
    """기록 본문·제목에 실제로 심겨 있는 값만(시험이 표를 낼 때 분모)."""
    haystack = "\n".join(f"{t}\n{b}" for _, t, b, _ in RECORDS)
    return [p for p in PLANTED if leaked(p, haystack)]


def build_world(client, monkeypatch) -> SimpleNamespace:
    """가족 그룹(구성원 5명, 표시 이름)과 기록 28개를 만든다. AI 동의를 켜고 쿨다운을 없앤다."""
    from app.shared.config import settings

    monkeypatch.setattr(settings, "ai_request_cooldown_seconds", 0)
    heads = [signup(client, real) for real, _ in MEMBERS]
    owner = heads[0]
    group = client.post("/family-group/groups", json={"name": "가짜 가족"}, headers=owner).json()
    for head in heads[1:]:
        join_family(client, owner, group["invite_code"], head)
    for head, (_, display) in zip(heads, MEMBERS, strict=True):
        if display:
            r = client.put(
                "/family-group/groups/me/profile", json={"display_name": display}, headers=head
            )
            assert r.status_code == 200, r.text
    r = client.put("/family-chat/ai/settings", json={"enabled": True}, headers=owner)
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.name == MEMBERS[0][0]))
        ids = []
        for kind, title, body, day in RECORDS:
            ids.append(
                service.ingest(
                    db,
                    group["id"],
                    user_id,
                    kind_label=kind,
                    title=title,
                    body_md=body,
                    occurred_on=day,
                ).id
            )
    return SimpleNamespace(
        heads=heads, owner=owner, group=group, group_id=group["id"], user_id=user_id, item_ids=ids
    )
