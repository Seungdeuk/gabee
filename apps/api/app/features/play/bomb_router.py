"""가족 놀이터 문장 폭탄방 API. 화면이 1초쯤마다 `GET /play/bomb/{id}` 를 불러 방 상태를 받는다(폴링)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import bomb
from .bomb_schemas import (
    PlayBombChatIn,
    PlayBombCheerIn,
    PlayBombSayIn,
    PlayBombStartIn,
    PlayBombStateOut,
    PlayBombVoteIn,
    PlayBombVoteStartIn,
)

router = APIRouter(prefix="/bomb")


@router.get("/current", response_model=PlayBombStateOut | None)
def current(
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayBombStateOut | None:
    """우리 가족의 열려 있는 폭탄방(없으면 null). 가족마다 한 번에 하나만 열 수 있다."""
    return bomb.current_room(db, user, group_id)


@router.post("", response_model=PlayBombStateOut, status_code=201)
def create(
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayBombStateOut:
    """폭탄방을 연다(방장). 이미 열린 방이 있으면 409 room_open."""
    return bomb.create_room(db, user, group_id)


@router.get("/{room_id}", response_model=PlayBombStateOut)
def get_room(
    room_id: str,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayBombStateOut:
    """방 상태: 선수·생명, 지금 차례와 남은 시간, 채팅, 판이 끝났으면 결과. 제한 시간이 지난 차례는 이때 시간 초과로 기록한다."""
    return bomb.get_room(db, user, group_id, room_id)


@router.post("/{room_id}/join", response_model=PlayBombStateOut)
def join(
    room_id: str,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayBombStateOut:
    """방에 들어온다. 게임이 시작된 뒤에 들어오면 이번 판은 구경한다."""
    return bomb.join_room(db, user, group_id, room_id)


@router.post("/{room_id}/leave", response_model=PlayBombStateOut)
def leave(
    room_id: str,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayBombStateOut:
    """방을 나간다(방장은 불가). 게임 중에 나가면 탈락한다."""
    return bomb.leave_room(db, user, group_id, room_id)


@router.post("/{room_id}/start", response_model=PlayBombStateOut)
def start(
    room_id: str,
    body: PlayBombStartIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayBombStateOut:
    """게임 시작 또는 한 판 더(방장). 생명 1~5, 차례당 1~60초. 방에 2명 이상 있어야 한다."""
    return bomb.start_round(db, user, group_id, room_id, body)


@router.post("/{room_id}/say", response_model=PlayBombStateOut)
def say(
    room_id: str,
    body: PlayBombSayIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayBombStateOut:
    """내 차례에 이어 말한다(10자까지). 이어 말한 문장이 끝났다고 판정되면 생명이 줄어든다."""
    return bomb.say(db, user, group_id, room_id, body.word)


@router.post("/{room_id}/cheer", response_model=PlayBombStateOut)
def cheer(
    room_id: str,
    body: PlayBombCheerIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayBombStateOut:
    """탈락했거나 구경하는 사람의 응원. 정해진 말을 고르거나 직접 쓴다(20자). 모두에게 보이고 한 사람이 2초에 한 번이다(429 cheer_cooldown)."""
    return bomb.cheer(db, user, group_id, room_id, body.text)


@router.post("/{room_id}/vote/start", response_model=PlayBombStateOut)
def vote_start(
    room_id: str,
    body: PlayBombVoteStartIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayBombStateOut:
    """판정 투표를 연다. call 어라?(다른 사람의 방금 말이 끝난 말인데 통과됐다, 살아있는 사람), unfair 억울해요(끝난 말이 아닌데 탈락한 본인). 한 사람이 한 판에 종류마다 한 번."""
    return bomb.start_vote(db, user, group_id, room_id, body.kind)


@router.post("/{room_id}/vote", response_model=PlayBombStateOut)
def vote(
    room_id: str,
    body: PlayBombVoteIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayBombStateOut:
    """열린 판정 투표에 찬성/반대를 고른다(살아있는 사람, 한 번). 안 고르면 기권이고, 찬성이 반대보다 많고 2표 이상이면 통과한다."""
    return bomb.cast_vote(db, user, group_id, room_id, body.yes)


@router.post("/{room_id}/chat", response_model=PlayBombStateOut)
def chat(
    room_id: str,
    body: PlayBombChatIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayBombStateOut:
    """탈락했거나 구경하는 사람끼리의 채팅(50자). 그런 사람들에게만 보이고 한 사람이 2초에 한 번이다(429 chat_cooldown)."""
    return bomb.chat(db, user, group_id, room_id, body.text)


@router.post("/{room_id}/close", response_model=PlayBombStateOut)
def close(
    room_id: str,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PlayBombStateOut:
    """방을 닫는다(방장, 게임 중에는 불가)."""
    return bomb.close_room(db, user, group_id, room_id)
