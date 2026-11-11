"""실제 문서 평가셋의 양식 목록과 내려받기(법제처 국가법령정보센터 별표·서식 PDF).

양식은 모두 법령의 별지 서식이다. 법령은 저작권법 제7조(보호받지 못하는 저작물)에 해당해 자유롭게 쓸 수 있다.
받은 파일은 실행하지 않고 PDF 로만 연다(신뢰하지 않는 데이터). 빈 서식만 쓰며 실제 개인정보가 든 문서는 받지 않는다.
"""

import html
import re
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

BASE = "https://www.law.go.kr/LSW/"

# slug, 법령명, 서식 시퀀스(bylSeq), 종류, 사람이 읽는 이름
FORMS = [
    (
        "medical_receipt",
        "국민건강보험 요양급여의 기준에 관한 규칙",
        18095215,
        "영수증",
        "진료비 계산서·영수증(외래·입원)",
    ),
    (
        "pharmacy_receipt",
        "국민건강보험 요양급여의 기준에 관한 규칙",
        18095223,
        "영수증",
        "약제비 계산서·영수증",
    ),
    (
        "simple_receipt",
        "국민건강보험 요양급여의 기준에 관한 규칙",
        18095227,
        "영수증",
        "간이 외래 진료비 계산서·영수증",
    ),
    (
        "payment_confirm",
        "국민건강보험 요양급여의 기준에 관한 규칙",
        18095229,
        "확인서",
        "진료비(약제비) 납입 확인서",
    ),
    ("prescription", "의료법 시행규칙", 18190665, "처방전", "처방전"),
    ("diagnosis", "의료법 시행규칙", 18190653, "확인서", "진단서"),
    ("donation_receipt", "소득세법 시행규칙", 18161573, "영수증", "기부금영수증"),
    ("insurance_premium_cert", "소득세법 시행규칙", 18161557, "보험", "보험료납입증명서"),
    ("education_fee_cert", "소득세법 시행규칙", 18161563, "확인서", "교육비납입증명서"),
    ("wage_withholding", "소득세법 시행규칙", 18161421, "확인서", "근로소득 원천징수영수증"),
    ("tax_notice", "국세징수법 시행규칙", 18024073, "고지서", "납부고지서(국세)"),
    ("local_tax_notice", "지방세법 시행규칙", 18191325, "고지서", "납세고지서(지방세)"),
    ("property_tax_notice", "지방세법 시행규칙", 18191529, "고지서", "주택 재산세 납세고지서"),
    (
        "car_tax_notice",
        "지방세법 시행규칙",
        18191569,
        "고지서",
        "자동차세(소유분) 납세고지서 겸 영수증",
    ),
    ("move_in_report", "주민등록법 시행규칙", 18503981, "신청서", "전입신고서"),
    (
        "move_in_cert_request",
        "주민등록법 시행규칙",
        18504019,
        "신청서",
        "전입세대확인서 열람 또는 교부 신청서",
    ),
    ("car_transfer_cert", "자동차등록규칙", 18175427, "계약서", "자동차양도증명서"),
    ("car_transfer_request", "자동차등록규칙", 18175425, "신청서", "이전등록 신청서"),
    ("medical_care_claim", "국민건강보험법 시행규칙", 18482079, "보험", "요양비 지급청구서"),
    (
        "premium_quarterly",
        "국민건강보험법 시행규칙",
        18482119,
        "신청서",
        "건강보험료 분기납부 신청서",
    ),
    (
        "exam_score_cert",
        "초ㆍ중등교육법 시행규칙",
        18002353,
        "확인서",
        "중학교 졸업학력 검정고시 성적증명서",
    ),
    (
        "business_account_report",
        "소득세법 시행규칙",
        18161461,
        "신청서",
        "사업용계좌신고(변경신고ㆍ추가신고)서",
    ),
    (
        "refund_account_report",
        "지방세기본법 시행규칙",
        18502905,
        "신청서",
        "지방세환급금 지급계좌 개설(변경)신고서",
    ),
    (
        "card_receipt_summary",
        "부가가치세법 시행규칙",
        18044617,
        "영수증",
        "신용카드매출전표등 수령명세서",
    ),
]

_UA = {"User-Agent": "Mozilla/5.0"}


def _get(url: str, data: str | None = None, binary: bool = False):
    req = urllib.request.Request(url, data=data.encode() if data else None, headers=_UA)
    raw = urllib.request.urlopen(req, timeout=60).read()
    return raw if binary else raw.decode("utf-8", "replace")


def resolve(law: str, seq: int) -> dict:
    """법령명과 서식 시퀀스로 PDF 시퀀스·시행일·서식 이름을 알아낸다."""
    page = _get(
        BASE
        + "lsBylInfoPLinkR.do?lsNm="
        + urllib.parse.quote(law)
        + "&bylNo=0001&bylBrNo=00&bylCls=BE"
    )
    first = re.search(r'id="bylSeq"[^>]*value="(\d+)"', page).group(1)
    lsi = re.search(r'id="lsiSeq"[^>]*value="(\d+)"', page).group(1)
    listing = _get(BASE + "lsBylInfoR.do", f"bylSeq={first}&lsiSeq={lsi}&vSct=*&efYd=")
    ls_id = re.search(r'id="bylLsId"[^>]*value="(\d+)"', listing).group(1)
    effective = re.search(r"\[시행 ([\d. ]+\.)\]", listing).group(1)
    for value, title in re.findall(r'<option value="([^"]+)"[^>]*>([^<]+)</option>', listing):
        parts = value.split(",")
        if parts[0] == str(seq):
            body = _get(
                BASE + "lsBylContentsInfoR.do",
                f"lsiSeq={seq}&bylNo={parts[1]}&bylBrNo={parts[2]}&bylClsCd={parts[3]}"
                f"&lsId={ls_id}&bylSeq={seq}&bylEfYd={parts[4]}&vSct=*&directYn=",
            )
            pdf_seq = re.search(r'id="pdfFlSeq"[^>]*value="(\d+)"', body).group(1)
            return {
                "title": html.unescape(title),
                "effective": effective,
                "pdf_seq": pdf_seq,
                "page_url": BASE
                + "lsBylInfoPLinkR.do?lsNm="
                + urllib.parse.quote(law)
                + f"&bylNo={parts[1]}&bylBrNo={parts[2]}&bylCls=BE",
                "download_url": BASE + f"flDownload.do?flSeq={pdf_seq}",
            }
    raise LookupError(f"{law} 에서 서식 {seq} 를 못 찾았어요")


def fetch_all(dest: Path) -> list[dict]:
    """양식 PDF 를 dest 에 받고 출처 기록 목록을 돌려준다. 이미 받은 파일은 다시 받지 않는다."""
    dest.mkdir(parents=True, exist_ok=True)
    rows = []
    for slug, law, seq, kind, name in FORMS:
        info = resolve(law, seq)
        path = dest / f"{slug}.pdf"
        if not path.exists():
            data = _get(info["download_url"], binary=True)
            if not data.startswith(b"%PDF"):
                raise ValueError(f"{slug}: PDF 가 아니에요")
            path.write_bytes(data)
        rows.append(
            {
                "slug": slug,
                "kind": kind,
                "name": name,
                "law": law,
                "law_form_title": info["title"],
                "law_effective": info["effective"],
                "source_page": info["page_url"],
                "download_url": info["download_url"],
                "publisher": "법제처 국가법령정보센터(www.law.go.kr) 별표·서식",
                "license": "법령의 별지 서식: 저작권법 제7조(법령은 보호받지 못하는 저작물)로 자유 이용. 빈 서식이며 실제 개인정보 없음",
                "fetched": date.today().isoformat(),
                "file": f"forms/{slug}.pdf",
            }
        )
    return rows
