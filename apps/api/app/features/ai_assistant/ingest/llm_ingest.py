"""Claude 로 업로드 글을 읽고 가린다(docs/adr/0014, 설정 `INGEST_LLM_OCR`·`INGEST_LLM_MASK`).

    글 ─▶ (코드) 가족 이름 후보 찾기 ─▶ (Claude 1회) 후보가 가족 본인인지 문맥 판단 + 그 밖의 개인정보를 원문 그대로 인용
       ─▶ (코드) 인용이 원문에 있는지 확인 → [가족:id]·[이름] 등으로 바꾸기 → 번호 규칙으로 남은 번호 한 번 더 가리기

원칙: Claude 는 "어디를 가릴지"만 알려 주고, 글을 바꾸는 일은 코드가 한다(글을 다시 쓰게 하면 가릴 곳이 아닌 곳까지 바뀌고, 검증할 수 없다).
Claude 호출이 실패하면(LLMUnavailable) 가리지 않은 글을 저장하지 않도록 예외를 그대로 올린다 — 호출한 쪽이 파일을 failed 로 둔다.
가린 값은 어디에도 남기지 않는다. 가린 개수만 센다.
"""

import io
import logging
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from app.shared.config import settings
from app.shared.llm import consent_gate, doc_ai
from app.shared.privacy.detectors import detect
from app.shared.privacy.types import Kind

from . import masking

logger = logging.getLogger(__name__)

# 가린 자리에 남기는 표시(이름·주소 같은 값은 되돌리지 않는다. 가족 이름은 [가족:id] 로 되돌린다)
TOKENS = {
    "PERSON": "[이름]",
    "ADDRESS": "[주소]",
    "PHONE": "[연락처]",
    "EMAIL": "[이메일]",
    "RRN": "[주민번호]",
    "CARD": "[카드번호]",
    "ACCOUNT": "[계좌번호]",
    "BIRTH": "[생년월일]",
    "ID_NUMBER": "[신분증번호]",
    "SECRET": "[비밀번호]",
}
_NUMERIC = {Kind.PHONE, Kind.EMAIL, Kind.RRN, Kind.CARD, Kind.ACCOUNT, Kind.SECRET}
# 앞의 라벨이 개인과 무관한 번호(거래·주문·승인·운송장·사업자등록 번호 등)를 뜻하면 전화·계좌 규칙의 안전망에서 뺀다.
# 접두어 없는 8자리(전화 "2027-4907")와 10~14자리 숫자(계좌 "110123456789")는 모양만으로는 주문번호·거래번호와 구별되지 않기 때문이다
_NON_PERSONAL_LABEL = re.compile(
    r"(거래|주문|승인|접수|운송장|송장|사업자|문서|관리|고유|전표|일련)\s*번호\s*[:：]?\s*$"
)
_LABEL_SENSITIVE = {Kind.PHONE, Kind.ACCOUNT}
# 주소 안전망: 시·도로 시작하고 아파트 동·호수(104동 1507호)까지 이어진 주소만 가린다. 동·호수는 집 주소의 표지라
# 병원·가게·관공서 주소(도로명+번호까지)는 건드리지 않는다. 칸 구분(|)·줄바꿈은 넘지 않는다.
# 시·도는 약칭(충남)과 정식 이름(충청남도·전라북도·경상남도·특별시·광역시·특별자치도)을 모두 받는다
_ADDRESS_NET = re.compile(
    r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|제주"
    r"|충청[남북]|충[남북]|전라[남북]|전[남북]|경상[남북]|경[남북])"
    r"[가-힣]*[^\n|]{2,60}?\d+\s*동\s*\d+\s*호"
)
# 사업장 라벨(사업장 소재지·영업소·상호 …) 옆의 주소는 가게·병원 주소라 안전망을 적용하지 않는다.
# 같은 줄에 사람 항목 라벨(신청인·신고인·보호자·세대주·수령인·거주지 …)이 사업장 라벨 뒤에 다시 나오면 집 주소로 본다
_BUSINESS_LABEL = re.compile(
    r"(사업장|소재지|영업소|사업자|상호|가맹점|판매점|판매자|판매원|제조원|제조사|수입원|수입자|본점|지점|매장|점포|병원|의원|약국|대표자)"
)
_PERSON_LABEL = re.compile(
    r"(신청인|신고인|보호자|세대주|수령인|수취인|받는\s*분|거주지|현\s*주소|자택|집\s*주소|배송지)"
)
MAX_SPAN = (
    200  # 이보다 긴 인용은 개인정보 한 덩어리로 보지 않는다(글 전체를 가리게 하는 지시문·오류 방지)
)
CONTEXT_PAD = 12  # 가족 후보 목록에 붙이는 앞뒤 글자 수
OCR_SIDE = 1900  # 사진을 보낼 때 긴 변(서버가 줄여 보내는 값과 같다)
_MARKS = re.compile(r"\s*\[\?\]")


def _strip(text: str) -> str:
    return "".join(ch for ch in text if ch not in doc_ai.INVISIBLE)


# ---------- 읽기 ----------
def ocr_image(image: Image.Image) -> doc_ai.OcrOut:
    img = image.convert("RGB")
    if max(img.size) > OCR_SIDE:
        img.thumbnail((OCR_SIDE, OCR_SIDE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return doc_ai.read_image(buf.getvalue())


def split_pdf_pages(data: bytes, limit: int) -> tuple[list[bytes], int]:
    """PDF 를 한 쪽짜리 PDF 들로 나눈다(앞 limit 쪽). (쪽 PDF 목록, 전체 쪽 수)"""
    import pypdfium2 as pdfium

    from .converters import BrokenFile

    try:
        doc = pdfium.PdfDocument(data)
    except Exception as e:  # 암호가 걸렸거나 깨진 PDF
        raise BrokenFile(f"PDF 를 열 수 없어요 ({type(e).__name__})") from None
    try:
        total = len(doc)
        pages: list[bytes] = []
        for i in range(min(total, limit)):
            one = pdfium.PdfDocument.new()
            one.import_pages(doc, [i])
            buf = io.BytesIO()
            one.save(buf)
            one.close()
            pages.append(buf.getvalue())
        return pages, total
    except Exception as e:
        raise BrokenFile(f"PDF 쪽을 나눌 수 없어요 ({type(e).__name__})") from None
    finally:
        doc.close()


def ocr_pdf(data: bytes) -> tuple[str, str | None]:
    """PDF 쪽마다 Claude 로 읽는다. (쪽을 \\f 로 이은 글, 확인이 필요한 이유)"""
    limit = settings.ingest_pdf_max_pages
    pages, total = split_pdf_pages(data, limit)
    with ThreadPoolExecutor(max_workers=4) as ex:
        outs = list(
            ex.map(consent_gate.carry(doc_ai.read_pdf), pages)
        )  # 동의 관문 범위를 작업 스레드로 넘긴다
    notes = []
    if total > len(pages):
        notes.append(f"앞 {len(pages)}쪽만 읽었어요(전체 {total}쪽)")
    if any(o.truncated for o in outs):
        notes.append("글이 많은 쪽은 뒷부분이 잘렸을 수 있어요")
    return "\f".join(o.text for o in outs), (". ".join(notes) or None)


def line_confidence(text: str) -> tuple[list[str], list[float]]:
    """줄마다 자신 없음 표시([?])를 떼고 확신도(0.5/0.9)를 돌려준다. 기존 확신도 기반 [불확실] 표시와 이어진다."""
    lines, conf = [], []
    for line in text.split("\n"):
        doubt = "[?]" in line
        lines.append(_MARKS.sub("", line) if doubt else line)
        conf.append(0.3 if "[판독불가]" in line else 0.5 if doubt else 0.9)
    return lines, conf


# ---------- 가리기 ----------
def split_chunks(text: str, limit: int) -> list[str]:
    """글을 limit 글자 안팎으로 나눈다(쪽 \\f → 빈 줄 → 줄바꿈 순으로 끊고, 이어 붙이면 원래 글이 된다)."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    for page in re.split(r"(?<=\f)", text):
        paras = re.split(r"(?<=\n\n)", page)
        buf = ""
        for p in paras:
            while len(p) > limit:  # 한 문단이 너무 길면 줄 → 글자 수로 끊는다
                cut = p.rfind("\n", 0, limit)
                cut = cut + 1 if cut > 0 else limit
                if buf:
                    parts.append(buf)
                    buf = ""
                parts.append(p[:cut])
                p = p[cut:]
            if len(buf) + len(p) > limit and buf:
                parts.append(buf)
                buf = ""
            buf += p
        if buf:
            parts.append(buf)
    return parts


def _locate(text: str, items: list[doc_ai.PiiItem]) -> tuple[list[tuple[int, int, str]], int]:
    """인용을 원문 위치로 바꾼다(같은 값은 문서 안에서 전부). 원문에 없는 인용은 세어서 버린다."""
    spans: list[tuple[int, int, str]] = []
    ungrounded = 0
    for it in items:
        q = it.text.strip()
        if len(q) < 2 or len(q) > MAX_SPAN:
            continue
        found, pos = False, 0
        while (k := text.find(q, pos)) >= 0:
            spans.append((k, k + len(q), it.kind))
            found, pos = True, k + len(q)
        if not found:
            ungrounded += 1
    return spans, ungrounded


def _apply(text: str, spans: list[tuple[int, int, str]], counts: Counter) -> str:
    """겹치면 먼저 시작한(같으면 긴) 것만. kind 가 '가족:<id>' 이면 [가족:<id>], 아니면 TOKENS 의 표시로 바꾼다."""
    out, pos = [], 0
    for a, b, kind in sorted(spans, key=lambda s: (s[0], -s[1])):
        if a < pos:
            continue
        if kind.startswith("가족:"):
            token = f"[{kind}]"
            counts["family"] += 1
        elif kind.startswith(
            "확인:"
        ):  # 가족 이름과 한 글자 차이인 이름: 사용자가 같은 사람인지 확인할 때까지 표시만 남긴다
            token = f"[확인필요:{kind.removeprefix('확인:')}]"
            counts["name_check"] += 1
        else:
            token = TOKENS.get(kind)
            if token is None:
                continue
            counts[kind.lower()] += 1
        out.append(text[pos:a])
        out.append(token)
        pos = b
    out.append(text[pos:])
    return "".join(out)


def _candidate_lines(chunk: str, cands: list) -> list[str]:
    lines = []
    for i, c in enumerate(cands, 1):
        pre = chunk[max(0, c.start - CONTEXT_PAD) : c.start].replace("\n", " ")
        post = chunk[c.end : c.end + CONTEXT_PAD].replace("\n", " ")
        lines.append(f"{i}. …{pre}[[{c.spelling}]]{post}…")
    return lines


def _near_family(items: list[doc_ai.PiiItem], family) -> list[doc_ai.PiiItem]:
    """Claude 가 이름으로 본 값이 가족 이름과 한 글자 차이면 종류를 '확인:<user_id>' 로 바꾼다(OCR 오독일 수 있어 사용자에게 물어본다)."""
    if family is None:
        return items
    out = []
    for it in items:
        uid = family.near_member(it.text) if it.kind == "PERSON" else None
        out.append(doc_ai.PiiItem(it.text, f"확인:{uid}") if uid else it)
    return out


def _numeric_net(text: str, counts: Counter) -> str:
    """Claude 가 놓친 번호(전화·이메일·주민·카드·계좌·비밀번호)를 규칙으로 한 번 더 가린다. 번호는 규칙이 검산까지 해서 정확하다."""
    spans = [
        (s.start, s.end, str(s.kind))
        for s in detect(text)
        if s.kind in _NUMERIC
        and not (
            s.kind in _LABEL_SENSITIVE
            and _NON_PERSONAL_LABEL.search(text[max(0, s.start - 12) : s.start])
        )
    ]
    return _apply(text, spans, counts)


def _is_business_address(text: str, start: int) -> bool:
    """주소 앞(같은 줄, 줄 앞쪽이 비었으면 윗줄까지)에 사업장 라벨이 있고, 그 뒤에 사람 항목 라벨이 없으면 True."""
    line_start = text.rfind("\n", 0, start) + 1
    before = text[line_start:start]
    if len(re.sub(r"[\s|:：]", "", before)) <= 2 and line_start > 0:
        prev_start = text.rfind("\n", 0, line_start - 1) + 1
        before = text[prev_start:start]
    before = before[-80:]
    last_business = None
    for m in _BUSINESS_LABEL.finditer(before):
        last_business = m
    if last_business is None:
        return False
    return _PERSON_LABEL.search(before, last_business.end()) is None


def _address_net(text: str, counts: Counter) -> str:
    """Claude 가 놓친 동·호수까지 있는 집 주소를 규칙으로 한 번 더 가린다. 사업장 라벨 옆 주소는 건드리지 않는다."""
    return _apply(
        text,
        [
            (m.start(), m.end(), "ADDRESS")
            for m in _ADDRESS_NET.finditer(text)
            if not _is_business_address(text, m.start())
        ],
        counts,
    )


def mask(text: str, family=None) -> tuple[str, dict[str, int], str]:
    """(가린 글, 종류별 가린 개수, 문서 종류 sensitive). Claude 호출이 실패하면 LLMUnavailable 을 그대로 올린다."""
    raw = _strip(text)
    sensitive = masking.sensitive_kind(
        raw
    )  # 분류가 쓰는 민감 문서 판별(처방전·신분증 …). 가리는 범위와는 상관없다
    counts: Counter = Counter()
    parts, ungrounded = [], 0
    for chunk in split_chunks(raw, settings.ingest_mask_chunk_chars):
        if not chunk.strip():
            parts.append(chunk)
            continue
        cands = family.candidates(chunk) if family is not None else []
        found = doc_ai.find_pii(chunk, _candidate_lines(chunk, cands))
        # 가족 후보를 먼저 둔다: Claude 가 같은 자리를 PERSON 으로도 보고하면 겹친 자리에서 가족 이름표가 이기게
        # (답이 빠진 후보는 가족으로 본다: 가려도 안전하고 예전 동작과 같다)
        family_spans = []
        for i, c in enumerate(cands, 1):
            if found.family.get(i, True):
                family_spans.append((c.start, c.end, f"가족:{c.user_id}"))
            elif len(c.spelling.replace(" ", "")) >= 3:
                # 가족으로 보지 않았어도 성+이름(세 글자 이상)이 그대로 남으면 실명이 새므로 일반 이름으로 가린다.
                # 두 글자 이름자('채용' 같은 낱말과 겹칠 수 있음)만 Claude 의 판단대로 둔다
                family_spans.append((c.start, c.end, "PERSON"))
        items = _near_family(found.items, family)
        pii_spans, bad = _locate(chunk, items)
        ungrounded += bad
        parts.append(_apply(chunk, family_spans + pii_spans, counts))
    masked = _address_net(_numeric_net("".join(parts), counts), counts)
    if ungrounded:
        logger.info("Claude 가 원문에 없는 인용 %d개를 보고해 버렸어요", ungrounded)
    return masked, {k: v for k, v in counts.items() if v}, sensitive
