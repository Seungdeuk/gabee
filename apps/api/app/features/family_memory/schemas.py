from datetime import datetime
from typing import Literal

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


class CandidatePhotoOut(BaseModel):
    """추억 후보에 든 사진 한 장. 사진 주소는 기존 채팅 사진 권한 체계를 그대로 쓴다(방에 들어갈 수 있는 가족만 볼 수 있다)."""

    attachment_id: str
    thumb_url: str
    photo_url: str
    taken_at: datetime | None  # 촬영 시각이 없으면 null(업로드 시각으로 대신하지 않는다)
    is_representative: bool


class CandidateOut(BaseModel):
    """비공개 추억 후보(PR7 앱이 쓰는 조회 계약). 조회할 때마다 자격을 다시 확인한 결과이며, 빠진 사진의 정보는 어디에도 없다."""

    id: str  # 후보 식별자(가족+포함 사진으로 정해지는 결정적 값, 사진이 바뀌면 달라진다)
    status: Literal["private"]  # 자동 게시하지 않는다
    representative: CandidatePhotoOut
    photos: list[CandidatePhotoOut]
    photo_count: int
    dated_count: int  # 촬영 시각이 있는 사진 수
    undated_count: int
    starts_at: datetime | None  # 남은 사진의 촬영 시각 범위(없으면 null)
    ends_at: datetime | None
    bridged: bool  # 하룻밤 이상 이어진 이벤트 후보인가
    score: float  # 0~1, 후보 우선순위용(정답 확률이 아니다)
    algorithm_version: str
    updated_at: datetime


class CandidatesOut(BaseModel):
    items: list[CandidateOut]
