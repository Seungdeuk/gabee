from typing import Literal

from pydantic import BaseModel, Field

FileKind = Literal["image", "pdf", "docx", "xlsx", "pptx", "text", "csv", "html", "unsupported"]
BlockType = Literal["heading", "paragraph", "table", "list", "ocr_line"]
QualityStatus = Literal["ok", "partial", "failed"]
Route = Literal["document", "daily_share", "review"]

PROCESSOR_VERSION = "ingest/2"


class SourceInfo(BaseModel):
    filename: str
    kind: FileKind
    mime: str
    size: int
    sha256: str


class Block(BaseModel):
    index: int = 0  # 파일 안에서의 순번(0부터) — 근거 표시용 "몇 번째 블록"
    type: BlockType
    text: str
    page: int | None = None  # PDF 쪽 · PPT 슬라이드 · 엑셀 시트 번호(1부터). 없으면 None
    sheet: str | None = None  # 엑셀 시트 이름
    level: int | None = None  # heading 의 단계(1~6)
    confidence: float | None = None  # ocr_line 의 글자 인식 확신도(0~1)


class Content(BaseModel):
    text: str = ""  # 전체 글자(마크다운)
    blocks: list[Block] = Field(default_factory=list)
    pages: int | None = None


class Quality(BaseModel):
    status: QualityStatus
    text_confidence: float | None = None
    warnings: list[str] = Field(default_factory=list)
    # failed 일 때 이유 코드: empty_file, too_large, unsupported_type, broken_file
    error: str | None = None


class Privacy(BaseModel):
    # 처방전·신분증·통장·가족관계증명서면 민감 문서(개인정보를 모두 가림). none 이면 주민번호만
    sensitive: Literal["none", "prescription", "id_card", "bankbook", "family_cert"] = "none"
    # 가린 개수 (rrn, card, phone, …) — 가린 값 자체는 어디에도 남기지 않는다
    masked: dict[str, int] = Field(default_factory=dict)


class Amount(BaseModel):
    label: str = ""
    value: int


class Classification(BaseModel):
    """자동 분류 결과. 가린 글자만 보고 만든다 — 원본 글자·파일 이름은 분류기에 들어가지 않는다."""

    doc_type: str  # 자유 문구: "영수증", "학교 가정통신문", "아파트 관리비 고지서" …
    route: Route  # 앱 화면 이동: 문서 화면 / 가족 공유 / 사람 확인
    confidence: float = 0.0
    needs_review: bool = False
    # 누가 정했나: 규칙 / Jev(가린 글자) / 로컬 언어 모델 / 못 정함
    by: Literal["rule", "jev", "model", "none"] = "none"
    tags: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)  # YYYY-MM-DD
    amounts: list[Amount] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)
    fields: dict[str, str] = Field(default_factory=dict)  # 종류별 폼 칸 ("제출 기한": "2026-10-20")


class Caption(BaseModel):
    """글자 없는 사진에 로컬 이미지 모델이 붙인 설명. 사실과 다를 수 있어서 자동으로 만든 것임을 남긴다."""

    description: str
    keywords: list[str] = Field(default_factory=list)
    by: Literal["local_vlm"] = "local_vlm"


class PreprocessResult(BaseModel):
    """원본 전처리 결과. content 는 이미 가린 글자다. 다음 단계(자동 분류)와 knowledge 가 이 모양만 본다."""

    source: SourceInfo
    content: Content = Field(default_factory=Content)
    quality: Quality
    privacy: Privacy = Field(default_factory=Privacy)
    classification: Classification | None = None  # ingest_file 에서 가린 뒤에 붙는다
    caption: Caption | None = None  # 글자 없는 사진의 자동 설명 (이미지 모델이 있을 때)
    raw_path: str | None = None  # 원본 데이터 센터 안의 위치 (ingest_file 로 저장했을 때)
    display_path: str | None = None  # 사진의 화면용 사본(1080px WebP, 위치 정보 없음)
    processor_version: str = PROCESSOR_VERSION
