"""가족 채팅 AI 기능(대화 분석·답장 추천·대화 주제 추천)의 요청·응답과 AI 구조화 출력 스키마."""

from datetime import datetime

from pydantic import BaseModel, Field


class AiSettingsIn(BaseModel):
    enabled: bool


class AiLimitsOut(BaseModel):
    user_per_day: int
    group_per_day: int
    cooldown_seconds: int
    cache_ttl_seconds: int


class AiUsageOut(BaseModel):
    user_today: int  # 오늘 내가 쓴 AI 호출 수(캐시 적중은 세지 않는다)
    group_today: int


class AiSettingsOut(BaseModel):
    enabled: bool  # 가족 그룹이 AI 기능 사용에 동의했는지
    can_manage: bool  # 내가 켜고 끌 수 있는지(소유자·관리자)
    auto_analysis: bool  # 자동 분석(서버 설정, 기본 꺼짐)
    limits: AiLimitsOut
    usage: AiUsageOut


class RangeIn(BaseModel):
    """분석할 범위. after_id 를 주면 그 뒤의 대화, 아니면 최근 limit 개(둘 다 주면 after_id 뒤의 최근 limit 개)."""

    limit: int = Field(default=100, ge=1, le=200)
    after_id: int = Field(default=0, ge=0)


class PrivacyMeta(BaseModel):
    """AI 로 보낸 대화에서 개인정보를 어떻게 처리했는지의 **개수만**(글자·값·토큰 없음)."""

    masked: dict[str, int] = {}  # 종류별 가린 개수. 예: {"PHONE": 2, "PERSON": 5}
    blocked_messages: int = 0  # 민감정보가 있어 통째로 제외한 메시지 수


class AiMeta(BaseModel):
    cached: bool  # True 면 저장된 결과를 다시 보여 준 것이고 AI 를 부르지 않았다
    api_calls: int  # 이번 요청에서 실제로 AI 를 부른 횟수(0 또는 1)
    input_tokens: int
    output_tokens: int
    model: str | None = None
    message_count: int  # 분석에 쓴 메시지 수(글자 수 한도 때문에 오래된 것이 빠졌을 수 있다)
    from_message_id: int
    to_message_id: int
    generated_at: datetime
    privacy: PrivacyMeta | None = None  # 개인정보 처리 요약(개수만). 구 응답과 호환되도록 선택 필드


class PreviewLine(BaseModel):
    """AI(Claude)가 실제로 받게 될 한 줄. 개인정보는 토큰으로 가려져 있고 차단된 메시지는 자리표시 문구다."""

    id: int
    speaker: str  # 가명화된 발화자(예: [PERSON_1]). 가족 호칭(엄마·아빠)은 그대로
    text: str
    blocked: bool


class PreviewOut(BaseModel):
    """AI 를 부르기 전에 무엇이 나가는지 보여 주는 미리보기. 원문 개인정보·대응표는 담지 않는다."""

    message_count: int
    masked: dict[str, int]
    blocked_messages: int
    lines: list[PreviewLine]
    ai_enabled: bool  # 우리 가족이 AI 기능에 동의했는지(미리보기는 동의와 무관하게 볼 수 있다)
    sendable: bool  # 차단되지 않은 메시지가 AI 에 보낼 만큼(3개 이상) 있는지. False 면 분석·답장·주제는 400 too_few_messages


class ImportantMessage(BaseModel):
    message_id: int
    reason: str


class ScheduleCandidate(BaseModel):
    """일정 후보. 날짜·시간·장소가 대화에 없으면 null 이다(AI 가 지어내지 않는다). 사용자가 확인해야 일정으로 등록된다."""

    title: str
    date: str | None = None  # YYYY-MM-DD
    time: str | None = None  # HH:MM
    place: str | None = None
    source_message_ids: list[int] = []


class TodoCandidate(BaseModel):
    """할 일·부탁 후보. 담당자·기한이 불명확하면 null 이다. 사용자가 확인해야 등록된다."""

    title: str
    assignee_name: str | None = None
    due: str | None = None  # YYYY-MM-DD
    source_message_ids: list[int] = []


class AnalysisOut(BaseModel):
    summary: str
    important_messages: list[ImportantMessage]
    schedule_candidates: list[ScheduleCandidate]
    todo_candidates: list[TodoCandidate]
    replies: list[str] = []  # 답장 후보 0~3개(각 80자 이내). 구 응답과 호환되도록 기본값이 빈 목록
    topics: list[str] = []  # 대화 주제 후보 0~5개(각 40자 이내)
    meta: AiMeta


class RepliesOut(BaseModel):
    replies: list[str]
    meta: AiMeta


class TopicsOut(BaseModel):
    topics: list[str]
    meta: AiMeta


# ---- AI 에 요구하는 구조화 출력(JSON Schema) ----
def _nullable(kind: str) -> dict:
    return {"anyOf": [{"type": kind}, {"type": "null"}]}


_IDS = {"type": "array", "items": {"type": "integer"}}

ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "summary",
        "important_messages",
        "schedule_candidates",
        "todo_candidates",
        "replies",
        "topics",
    ],
    "properties": {
        "summary": {"type": "string"},
        "replies": {"type": "array", "items": {"type": "string"}},
        "topics": {"type": "array", "items": {"type": "string"}},
        "important_messages": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["message_id", "reason"],
                "properties": {"message_id": {"type": "integer"}, "reason": {"type": "string"}},
            },
        },
        "schedule_candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "date", "time", "place", "source_message_ids"],
                "properties": {
                    "title": {"type": "string"},
                    "date": _nullable("string"),
                    "time": _nullable("string"),
                    "place": _nullable("string"),
                    "source_message_ids": _IDS,
                },
            },
        },
        "todo_candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "assignee_name", "due", "source_message_ids"],
                "properties": {
                    "title": {"type": "string"},
                    "assignee_name": _nullable("string"),
                    "due": _nullable("string"),
                    "source_message_ids": _IDS,
                },
            },
        },
    },
}

REPLIES_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["replies"],
    "properties": {"replies": {"type": "array", "items": {"type": "string"}}},
}

TOPICS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["topics"],
    "properties": {"topics": {"type": "array", "items": {"type": "string"}}},
}
