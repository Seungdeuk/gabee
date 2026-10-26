"""프로필 사진 업로드 응답 모델."""

from datetime import datetime

from pydantic import BaseModel


class ProfilePhotoOut(BaseModel):
    photo_url: str | None = None  # 앱이 서버 주소 뒤에 붙여 인증 헤더와 함께 요청한다(없으면 null)
    photo_updated_at: datetime | None = None
