import re

from pydantic import BaseModel, Field, field_validator

# 영어 소문자·숫자·_·- 만, 40자까지. 들어온 값은 먼저 normalize_tag 로 다듬은 뒤 이 규칙으로 검사한다
TAG = r"^[a-z0-9_-]{1,40}$"

# 메타(페이스북·인스타그램) 광고는 utm_source 에 "apps.facebook.com" 같은 주소를 넣어 보낸다.
# 같은 채널로 묶이도록 알려진 주소·별칭을 채널 이름 하나로 바꾼다(앱 referrer.js 와 같은 표).
ALIASES = {
    "apps.facebook.com": "facebook",
    "m.facebook.com": "facebook",
    "l.facebook.com": "facebook",
    "lm.facebook.com": "facebook",
    "facebook.com": "facebook",
    "fb": "facebook",
    "facebook": "facebook",
    "instagram.com": "instagram",
    "l.instagram.com": "instagram",
    "ig": "instagram",
    "instagram": "instagram",
}


def normalize_tag(value: object) -> object:
    """utm 값을 규칙에 맞게 다듬는다: 앞뒤 공백 제거·소문자, 알려진 별칭은 채널 이름으로,
    그 밖의 허용되지 않는 글자(점 등)는 '-' 로 바꾸고 겹친 '-' 는 하나로, 앞뒤 '-' 는 빼고 40자까지.
    문자열이 아니면 그대로 돌려줘 Pydantic 이 형식 오류를 내게 한다. 다듬은 뒤 빈 값이면 TAG 검사에서 422."""
    if not isinstance(value, str):
        return value
    tag = value.strip().lower()
    if tag in ALIASES:
        return ALIASES[tag]
    tag = re.sub(r"[^a-z0-9_-]+", "-", tag)
    tag = re.sub(r"-{2,}", "-", tag).strip("-")
    return tag[:40].rstrip("-")


class InstallSourceIn(BaseModel):
    source: str = Field(pattern=TAG)  # utm_source
    medium: str | None = Field(default=None, pattern=TAG)  # utm_medium
    campaign: str | None = Field(default=None, pattern=TAG)  # utm_campaign

    @field_validator("source", "medium", "campaign", mode="before")
    @classmethod
    def _normalize(cls, value: object) -> object:
        return normalize_tag(value)
