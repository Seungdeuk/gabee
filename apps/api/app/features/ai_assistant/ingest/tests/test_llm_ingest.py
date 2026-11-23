"""Claude 로 읽고 가리는 업로드 경로(docs/adr/0010): 가짜 Claude 응답으로 시험한다. 외부 서비스는 부르지 않고, 값은 모두 가상이다."""

import io
from functools import partial

import httpx
import pytest
from PIL import Image

from app.features.ai_assistant.family_names import FamilyTagger, Member
from app.features.ai_assistant.ingest import converters, llm_ingest
from app.features.ai_assistant.ingest import service as _service
from app.shared.config import settings
from app.shared.llm import doc_ai, transport

# 이 시험은 외부 전송이 허용된 가족(동의 있음) 기준이다. `external` 은 필수 인자라 여기서 한 번만 넘긴다. 동의 없는 경우는 test_external_consent.py·test_consent_ingest_flow.py 가 본다.
preprocess = partial(_service.preprocess, external=True)


class FakeClaude:
    """transport.post_messages 대신 끼우는 가짜. 도구 호출(가리기)과 글 답(OCR)을 구분해 정해 둔 답을 준다."""

    def __init__(self):
        self.calls: list[dict] = []
        self.items: list[dict] = []
        self.family: dict[int, bool] = {}
        self.ocr_text = ""
        self.fail = False

    def __call__(self, body, *, timeout, retry):
        self.calls.append(body)
        if self.fail:
            raise httpx.ConnectError("연결 실패")
        usage = {"input_tokens": 10, "output_tokens": 5}
        if body.get("tools"):
            data = {"items": self.items}
            if "family_decisions" in body["tools"][0]["input_schema"]["properties"]:
                data["family_decisions"] = [
                    {"id": i, "is_family": v} for i, v in self.family.items()
                ]
            return {
                "content": [{"type": "tool_use", "id": "t1", "name": "report_pii", "input": data}],
                "usage": usage,
            }
        return {
            "content": [{"type": "text", "text": self.ocr_text}],
            "stop_reason": "end_turn",
            "usage": usage,
        }


@pytest.fixture
def claude(monkeypatch):
    fake = FakeClaude()
    monkeypatch.setattr(transport, "post_messages", fake)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "ingest_llm_mask", True)
    monkeypatch.setattr(settings, "ingest_llm_ocr", True)
    return fake


def item(text, kind):
    return {"text": text, "kind": kind}


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), "white").save(buf, "PNG")
    return buf.getvalue()


# ---------- 가리기: 인용 -> 코드가 바꾼다 ----------
def test_quoted_values_are_replaced_and_the_rest_is_untouched(claude):
    claude.items = [item("김민수", "PERSON"), item("010-1234-5678", "PHONE")]
    text = "환자 김민수 연락처 010-1234-5678\n병원 서울 강남구 테헤란로 1"
    masked, counts, _ = llm_ingest.mask(text)
    assert masked == "환자 [이름] 연락처 [연락처]\n병원 서울 강남구 테헤란로 1"
    assert counts == {"person": 1, "phone": 1}


def test_a_quote_that_is_not_in_the_text_is_ignored(claude):
    claude.items = [item("이름만지어냄", "PERSON")]
    masked, counts, _ = llm_ingest.mask("영수증 합계 12,000원")
    assert masked == "영수증 합계 12,000원" and counts == {}


def test_quote_too_long_to_be_one_value_is_ignored(claude):
    body = "가" * 300
    claude.items = [item(body, "PERSON")]  # 글 전체를 가리게 하는 지시문·오류를 막는다
    assert llm_ingest.mask(body)[0] == body


def test_every_occurrence_of_a_reported_value_is_masked(claude):
    claude.items = [item("박서준", "PERSON")]
    assert llm_ingest.mask("박서준 님, 박서준 학생")[0] == "[이름] 님, [이름] 학생"


def test_numbers_claude_missed_are_masked_by_the_rule_net(claude):
    claude.items = []
    masked, counts, _ = llm_ingest.mask("연락처 010-1234-5678")
    assert masked == "연락처 [연락처]" and counts == {"phone": 1}


def test_invisible_characters_are_removed_before_masking(claude):
    claude.items = []
    masked, _, _ = llm_ingest.mask("연락처 010-12​34-5678")
    assert "​" not in masked and "010" not in masked


def test_sensitive_kind_still_comes_from_the_text(claude):
    claude.items = []
    text = "처방전\n질병분류기호 J00\n투약일수 3\n조제 약국\n복용 법"
    assert llm_ingest.mask(text)[2] == "prescription"


# ---------- 가족 이름 후보: 코드가 찾고 Claude 가 문맥으로 판단 ----------
FAMILY = FamilyTagger([Member("u1", "채용")])


def test_family_candidates_follow_the_context_decision(claude):
    claude.family = {1: False, 2: True}  # 1번 "채용 공고"는 낱말, 2번 "채용이가"는 가족
    masked, counts, _ = llm_ingest.mask("신입 채용 공고. 어제 채용이가 전화했어", FAMILY)
    assert masked == "신입 채용 공고. 어제 [가족:u1]이가 전화했어"
    assert counts == {"family": 1}
    prompt = claude.calls[0]["messages"][0]["content"][0]["text"]
    assert "[[채용]]" in prompt  # 후보는 앞뒤 구절과 함께 목록으로 간다


def test_candidate_without_an_answer_is_tagged_as_family(claude):
    claude.family = {}  # Claude 가 답을 빠뜨려도 예전 동작(글자가 같으면 이름표)으로 안전하게
    masked, _, _ = llm_ingest.mask("신입 채용 공고. 어제 채용이가 전화했어", FAMILY)
    assert masked == "신입 [가족:u1] 공고. 어제 [가족:u1]이가 전화했어"


def test_family_tag_wins_when_claude_also_reports_the_same_place_as_a_person(claude):
    claude.family = {1: True}
    claude.items = [item("채용", "PERSON")]  # Claude 가 같은 자리를 PERSON 으로 중복 보고
    masked, counts, _ = llm_ingest.mask("성명 채용", FAMILY)
    assert masked == "성명 [가족:u1]" and counts == {"family": 1}


def test_order_number_after_its_label_is_not_masked_as_an_account(claude):
    claude.items = []
    text = "주문번호 6722588249\n운송장번호 123456789012\n납부계좌 신한은행 110-123-456789"
    masked, _, _ = llm_ingest.mask(text)
    assert "6722588249" in masked and "123456789012" in masked
    assert "110-123-456789" not in masked and "[계좌번호]" in masked


def test_short_number_after_a_non_personal_label_is_left_alone_but_a_phone_label_is_masked(claude):
    claude.items = []
    masked, _, _ = llm_ingest.mask(
        "거래번호:1389-0015 TEL. 02-3453-5448 문의 45599442 전화 2027-4907"
    )
    assert "1389-0015" in masked  # 거래번호는 전화번호가 아니다
    assert "3453" not in masked and "45599442" not in masked and "2027-4907" not in masked


def test_no_candidates_means_no_family_question(claude):
    claude.items = []
    llm_ingest.mask("오늘 날씨 좋다", FAMILY)
    assert "family_decisions" not in claude.calls[0]["tools"][0]["input_schema"]["properties"]


def test_same_name_for_two_members_is_not_a_candidate(claude):
    same = FamilyTagger([Member("s1", "강민훈"), Member("s2", "강민훈")])
    assert same.candidates("성명: 강민훈") == []


# ---------- 긴 글 나누기 ----------
def test_split_chunks_rebuilds_the_text_and_respects_the_limit():
    text = "\f".join("가나다 " * 40 + "\n\n" + "라마바 " * 40 for _ in range(4))
    parts = llm_ingest.split_chunks(text, 300)
    assert "".join(parts) == text
    assert all(len(p) <= 300 for p in parts)
    assert len(parts) > 4


def test_long_text_calls_claude_once_per_chunk(claude, monkeypatch):
    monkeypatch.setattr(settings, "ingest_mask_chunk_chars", 100)
    claude.items = []
    llm_ingest.mask("가나다라마바사 " * 40)
    assert len(claude.calls) > 1


# ---------- 실패: 가리지 않은 글을 저장하지 않는다 ----------
def test_claude_failure_fails_the_file_without_keeping_any_text(claude):
    claude.fail = True
    r = preprocess("환자 김민수".encode(), "메모.txt")
    assert r.quality.status == "failed" and r.quality.error == "llm_unavailable"
    assert r.content.text == "" and r.content.blocks == []


def test_missing_api_key_fails_the_file(claude, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    r = preprocess("환자 김민수".encode(), "메모.txt")
    assert r.quality.error == "llm_unavailable"


# ---------- 읽기(OCR) ----------
def test_image_text_comes_from_claude_and_doubtful_lines_lose_their_marker(claude):
    claude.ocr_text = "합계 12,000원 [?]\n\n상호 행복마트"
    claude.items = []
    r = preprocess(png(), "영수증.png")
    assert r.quality.status == "partial" and r.quality.warnings
    assert [b.text for b in r.content.blocks] == ["합계 12,000원", "상호 행복마트"]
    assert [b.confidence for b in r.content.blocks] == [0.5, 0.9]
    assert "[?]" not in r.content.text


def test_image_with_no_text_is_reported(claude):
    claude.ocr_text = ""
    r = preprocess(png(), "빈.png")
    assert r.quality.status == "ok" and "사진에 글자가 없어요" in r.quality.warnings


def test_unreadable_marker_lowers_confidence(claude):
    claude.ocr_text = "합계 [판독불가]원"
    claude.items = []
    r = preprocess(png(), "영수증.png")
    assert r.content.blocks[0].confidence == 0.3


def _pdf(pages: int) -> bytes:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(200, 200)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_pdf_pages_are_read_one_by_one_with_claude(claude, monkeypatch):
    claude.ocr_text = (
        "한 쪽에 적힌 글자가 이만큼 있어요"  # 20자 이상이어야 '스캔본' 경고가 먼저 붙지 않는다
    )
    claude.items = []
    monkeypatch.setattr(settings, "ingest_pdf_max_pages", 2)
    r = preprocess(_pdf(3), "문서.pdf")
    docs = [c for c in claude.calls if c["messages"][0]["content"][0]["type"] == "document"]
    assert len(docs) == 2  # 앞 2쪽만
    assert any("앞 2쪽만" in w for w in r.quality.warnings)


def test_ocr_flag_alone_uses_the_old_masking(monkeypatch, claude):
    monkeypatch.setattr(settings, "ingest_llm_mask", False)
    claude.ocr_text = "성명 홍길동\n주민등록번호 900101-1234567"
    r = preprocess(png(), "사진.png")
    assert "홍길동" not in r.content.text and "1234567" not in r.content.text  # 규칙 가리기
    assert all(not c.get("tools") for c in claude.calls)  # 가리기용 Claude 호출은 없다


def test_flags_off_never_call_claude(monkeypatch):
    fake = FakeClaude()
    monkeypatch.setattr(transport, "post_messages", fake)
    monkeypatch.setattr(settings, "ingest_llm_mask", False)
    monkeypatch.setattr(settings, "ingest_llm_ocr", False)
    preprocess("성명 홍길동".encode(), "메모.txt")
    assert fake.calls == []


# ---------- 래퍼 ----------
def test_sonnet_cannot_force_a_tool_so_the_wrapper_asks_for_it_in_words(claude, monkeypatch):
    monkeypatch.setattr(settings, "ingest_mask_model", "claude-sonnet-5-5")
    claude.items = []
    doc_ai.find_pii("글")
    body = claude.calls[0]
    assert body["tool_choice"] == {"type": "auto"} and body["system"].endswith("도구로만 답하세요.")


def test_haiku_forces_the_tool(claude, monkeypatch):
    monkeypatch.setattr(settings, "ingest_mask_model", "")
    claude.items = []
    doc_ai.find_pii("글")
    assert claude.calls[0]["tool_choice"] == {"type": "tool", "name": "report_pii"}


def test_unknown_kinds_from_claude_are_dropped(claude):
    claude.items = [item("김민수", "WEIRD"), item("이서연", "PERSON")]
    assert [i.text for i in doc_ai.find_pii("김민수 이서연").items] == ["이서연"]


# ---------- 엑셀: 서식 반영 변환 ----------
def test_xlsx_keeps_what_the_sheet_shows():
    import datetime as dt

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "11월"
    ws.merge_cells("A1:D1")
    ws["A1"] = "2026년 11월 지출"
    ws.append(["날짜", "항목", "금액", "비율"])
    ws.append([dt.datetime(2026, 10, 18), "교통카드", 53500, 0.255])
    ws["A3"].number_format = "yyyy-mm-dd"
    ws["C3"].number_format = "#,##0"
    ws["D3"].number_format = "0.0%"
    wb.create_sheet("숨김").sheet_state = "hidden"
    buf = io.BytesIO()
    wb.save(buf)
    md = converters.xlsx_to_markdown(buf.getvalue())
    assert "## 11월" in md and "숨김" not in md
    assert md.count("2026년 11월 지출") == 4  # 병합 칸은 걸친 칸마다 같은 값
    assert "| 2026-10-18 | 교통카드 | 53,500 | 25.5% |" in md
    assert "Unnamed" not in md and "00:00:00" not in md


def test_name_one_character_off_a_family_name_waits_for_the_user(claude):
    members = [Member("aaaa1111", "강민훈")]
    claude.items = [item("강민혼", "PERSON"), item("박서연", "PERSON")]
    text = "보호자 강민혼, 담당의 박서연"
    masked, counts, _ = llm_ingest.mask(text, FamilyTagger(members))
    # 한 글자 차이인 이름은 지우지 않고 '확인 대기' 표시만 남긴다(글자는 저장하지 않는다). 다른 사람 이름은 그대로 가린다
    assert masked == "보호자 [확인필요:aaaa1111], 담당의 [이름]"
    assert counts == {"name_check": 1, "person": 1}
    assert "강민혼" not in masked


def test_without_family_members_no_name_waits_for_the_user(claude):
    claude.items = [item("강민혼", "PERSON")]
    masked, counts, _ = llm_ingest.mask("보호자 강민혼")
    assert masked == "보호자 [이름]" and counts == {"person": 1}


def test_upload_reading_and_masking_use_claude_by_default():
    assert type(settings).model_fields["ingest_llm_ocr"].default is True
    assert type(settings).model_fields["ingest_llm_mask"].default is True


# ---------- 주소 안전망: 동·호수까지 있는 집 주소 ----------
def test_apartment_address_claude_missed_is_masked_by_the_rule_net(claude):
    claude.items = []
    text = "| 신청인 | 주소 서울특별시 가상구 테스트길 8, 104동 1507호 | 비고 |"
    masked, counts, _ = llm_ingest.mask(text)
    assert masked == "| 신청인 | 주소 [주소] | 비고 |" and counts == {"address": 1}


def test_address_net_does_not_cross_cells_and_leaves_business_addresses_alone(claude):
    claude.items = []
    text = "병원 서울특별시 강남구 테헤란로 152\n| 부산 | 합계 12,000원 | 104동 | 1507호 |\n2024년 5월 3일 경기 안내"
    masked, counts, _ = llm_ingest.mask(text)
    assert masked == text and counts == {}


def test_address_net_skips_business_location_even_with_dong_ho(claude):
    claude.items = []
    text = "| 사업장 소재지 | 대전광역시 샘플구 테스트길 80, 111동 1485호 |\n영업소 주소: 서울특별시 가상구 길 3, 2동 301호"
    masked, counts, _ = llm_ingest.mask(text)
    assert masked == text and counts == {}


def test_address_net_masks_person_address_after_a_business_label(claude):
    claude.items = []
    text = "사업장 상호 가비마트 / 신청인 주소 서울특별시 가상구 테스트길 8, 104동 1507호"
    masked, counts, _ = llm_ingest.mask(text)
    assert "104동" not in masked and counts == {"address": 1}


@pytest.mark.parametrize(
    "region",
    ["충청남도", "충청북도", "전라북도", "전라남도", "경상남도", "경상북도", "충남", "경북"],
)
def test_address_net_accepts_full_province_names(claude, region):
    claude.items = []
    masked, counts, _ = llm_ingest.mask(f"신청인 주소 {region} 가상시 테스트길 8, 104동 1507호")
    assert "104동" not in masked and counts == {"address": 1}


def test_address_reported_by_claude_is_not_counted_twice(claude):
    claude.items = [item("서울특별시 가상구 테스트길 8, 104동 1507호", "ADDRESS")]
    masked, counts, _ = llm_ingest.mask("주소 서울특별시 가상구 테스트길 8, 104동 1507호")
    assert masked == "주소 [주소]" and counts == {"address": 1}
