"""가족 놀이터: 비동기 놀이(골든벨·이게 뭐게·찰칵! 탐정단)를 만들고, 현황판을 보고, 답을 보내고, 순위를 본다."""

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import media, service
from .schemas import (
    PlayBoardOut,
    PlayDrawTryIn,
    PlayItemOut,
    PlayQuizAnswerIn,
    PlayQuizCreateIn,
    PlayQuotaOut,
    PlayRankingOut,
)

router = APIRouter(prefix="/play", tags=["play"])


@router.post("/quiz", response_model=PlayItemOut, status_code=201)
def create_quiz(
    body: PlayQuizCreateIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayItemOut:
    """골든벨 세트(1~5문항)를 낸다. 받는 사람을 비우면 가족 모두이고, 24시간 뒤(모두 답하면 그 순간) 닫힌다."""
    return service.create_quiz(db, user, group_id, body)


@router.post("/draws", response_model=PlayItemOut, status_code=201)
def create_draw(
    file: UploadFile = File(..., description="그림 PNG(2MB 이하)"),
    answer: str = Form(..., description="정답(40자 이하)"),
    alt_answers: list[str] = Form(default=[], description="이것도 정답(5개까지)"),
    hint2: str | None = Form(
        default=None, description="힌트 2(20자 이하). 힌트 1은 글자 수로 만든다"
    ),
    player_ids: list[str] = Form(default=[], description="받는 사람. 비우면 가족 모두"),
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayItemOut:
    """이게 뭐게 문제를 낸다(그림 + 정답). 파일은 서버 디스크에 두고 24시간 뒤 닫힌다."""
    data = file.file.read(media.DRAW_MAX_BYTES + 1)
    return service.create_draw(
        db,
        user,
        group_id,
        data=data,
        answer=answer,
        alt_answers=alt_answers,
        hint2=hint2,
        player_ids=player_ids,
    )


@router.post("/photos", response_model=PlayItemOut, status_code=201)
def create_photo(
    file: UploadFile = File(..., description="사진 JPEG/PNG/WebP(8MB 이하)"),
    source: int = Form(..., description="1 가족 앨범, 2 내 폰"),
    zoom: int = Form(..., description="확대 배율 4·6·8·16·32"),
    box_x: float = Form(..., ge=0, le=1, description="확대 창 가운데 가로 위치 0~1"),
    box_y: float = Form(..., ge=0, le=1, description="확대 창 가운데 세로 위치 0~1"),
    question: str = Form(..., description="질문(20자 이하)"),
    options: list[str] = Form(..., description="보기 2~4개"),
    answer_index: int = Form(..., ge=0, le=3, description="정답 보기 위치(0부터)"),
    comment: str | None = Form(default=None, description="한마디(100자 이하)"),
    player_ids: list[str] = Form(default=[], description="받는 사람. 비우면 가족 모두"),
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayItemOut:
    """찰칵! 탐정단 문제를 낸다(사진 + 확대 위치 + 선택식 보기)."""
    data = file.file.read(media.PHOTO_MAX_BYTES + 1)
    return service.create_photo(
        db,
        user,
        group_id,
        data=data,
        source=source,
        zoom=zoom,
        box_x=box_x,
        box_y=box_y,
        question=question,
        options=options,
        answer_index=answer_index,
        comment=comment,
        player_ids=player_ids,
    )


@router.get("/board", response_model=PlayBoardOut)
def board(
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayBoardOut:
    """놀이터 현황: 받은(내가 할 차례·참여했어요·지난 결과 3일)과 보낸(내가 낸 문제·지난 결과)."""
    return service.board(db, user, group_id)


@router.get("/items/{item_id}", response_model=PlayItemOut)
def get_item(
    item_id: str,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayItemOut:
    """문제 한 건. 정답은 낸 사람·이미 끝낸 사람·닫힌 뒤에만, 가족 모두의 답은 닫힌 뒤에만 보인다."""
    return service.get_item(db, user, group_id, item_id)


@router.get("/items/{item_id}/image")
def get_image(
    item_id: str,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Response:
    """그림(PNG) 또는 사진(JPEG). 탐정단은 푸는 중에는 확대한 조각만, 끝낸 뒤·낸 사람·닫힌 뒤에는 전체가 나간다."""
    data, mime = service.image_for(db, user, group_id, item_id)
    return Response(
        content=data, media_type=mime, headers={"Cache-Control": "private, max-age=3600"}
    )


@router.post("/items/{item_id}/answers", response_model=PlayItemOut)
def submit_answers(
    item_id: str,
    body: PlayQuizAnswerIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayItemOut:
    """골든벨은 문항 수만큼 한 번에, 탐정단은 보기 하나(quiz_no 0)를 보낸다. 보낸 답은 고칠 수 없다."""
    return service.submit_answers(db, user, group_id, item_id, body)


@router.post("/items/{item_id}/hints", response_model=PlayItemOut)
def open_hint(
    item_id: str,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayItemOut:
    """이게 뭐게 힌트 열기 / 탐정단 조금 줄여 보기. 한 번에 -5점(맞혔을 때), 최대 2번."""
    return service.open_hint(db, user, group_id, item_id)


@router.post("/items/{item_id}/tries", response_model=PlayItemOut)
def submit_try(
    item_id: str,
    body: PlayDrawTryIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayItemOut:
    """이게 뭐게 정답 쓰기(최대 10번). 틀려도 깎이지 않고, 맞히거나 10번을 다 쓰면 끝난다."""
    return service.submit_try(db, user, group_id, item_id, body)


@router.get("/quota", response_model=PlayQuotaOut)
def quota(
    user: User = Depends(current_user),
    _group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayQuotaOut:
    """오늘 내가 낸 문제 수와 문제 내기 점수(+20)를 받을 수 있는 남은 횟수."""
    return service.quota(db, user)


@router.get("/ranking", response_model=PlayRankingOut)
def ranking(
    period: Literal["week", "month", "all"] = Query("week"),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayRankingOut:
    """이번 주(월요일 시작)·이번 달·전체 순위. 점수 장부를 합산한다."""
    return service.ranking(db, group_id, period)
