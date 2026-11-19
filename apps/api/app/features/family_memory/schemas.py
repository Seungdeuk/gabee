from pydantic import BaseModel


class MyConsentOut(BaseModel):
    consented: bool  # 새 업로드 사진의 AI 분석 동의가 지금 유효한가
    retro_consented: bool  # 과거 사진 소급 분석 동의(별개, 기본 꺼짐)
    consent_version: int | None  # 동의한 문구 버전(미동의면 None)


class MemoryStateOut(BaseModel):
    server_enabled: bool  # 서버 기능 스위치(꺼져 있으면 아래가 모두 켜져 있어도 분석되지 않는다)
    family_enabled: bool  # 가족 관리자가 켠 가족 설정
    can_manage: bool  # 내가 가족 설정을 바꿀 수 있는가(소유자·관리자)
    me: MyConsentOut


class FamilyEnabledIn(BaseModel):
    enabled: bool


class ConsentIn(BaseModel):
    consent: bool


class ExclusionIn(BaseModel):
    excluded: bool


class ExclusionOut(BaseModel):
    attachment_id: str
    excluded: bool
