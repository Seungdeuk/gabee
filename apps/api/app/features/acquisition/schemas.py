from pydantic import BaseModel, Field

# 영어 소문자·숫자·_·- 만, 40자까지. 앱이 꼬리표에서 utm 값만 골라 소문자로 바꿔 보낸다
TAG = r"^[a-z0-9_-]{1,40}$"


class InstallSourceIn(BaseModel):
    source: str = Field(pattern=TAG)  # utm_source
    medium: str | None = Field(default=None, pattern=TAG)  # utm_medium
    campaign: str | None = Field(default=None, pattern=TAG)  # utm_campaign
