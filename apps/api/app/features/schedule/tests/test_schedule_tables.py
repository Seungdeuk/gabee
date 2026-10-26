"""일정 DB 구조: 새 컬럼의 기본값, 부탁·받는 사람·추천 테이블."""

from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.features.family_group.models import User
from app.shared.db import SessionLocal

from ..constants import (
    KIND_APPOINTMENT,
    RECIPIENT_ACCEPTED,
    RECIPIENT_WAITING,
    SUGGESTION_PENDING,
)
from ..models import Event, EventRequest, EventRequestRecipient, EventSuggestion


def _users(db):
    return list(db.scalars(select(User).order_by(User.name)))


def test_event_new_columns_have_defaults(client, family):
    """새 컬럼을 모르는 기존 코드가 insert 해도 기본값이 채워진다."""
    _, _, group = family
    with SessionLocal() as db:
        db.add(
            Event(
                id="e1",
                group_id=group["id"],
                title="병원",
                starts_at=datetime.now(UTC),
                created_by=_users(db)[0].id,
            )
        )
        db.commit()
        event = db.get(Event, "e1")
        assert event.kind == KIND_APPOINTMENT
        assert event.who_ids == []
        assert event.place == ""
        assert event.memo == ""
        assert event.checked is False
        assert event.user_id is None
        assert event.start_date is None
        assert event.deleted_at is None


def test_request_recipients_and_event_links(client, family):
    _, _, group = family
    with SessionLocal() as db:
        sender, receiver = _users(db)[:2]
        request = EventRequest(
            group_id=group["id"],
            user_id=sender.id,
            title="장보기",
            start_date=date(2026, 11, 3),
            start_time=time(10, 0),
            end_time=time(11, 0),
        )
        db.add(request)
        db.flush()
        recipient = EventRequestRecipient(
            group_id=group["id"], user_id=receiver.id, request_id=request.id
        )
        db.add(recipient)
        db.flush()
        assert recipient.status == RECIPIENT_WAITING
        assert request.canceled_at is None

        recipient.status = RECIPIENT_ACCEPTED
        recipient.answered_at = datetime.now(UTC)
        db.add(
            Event(
                id="e2",
                group_id=group["id"],
                title=request.title,
                starts_at=datetime.now(UTC),
                created_by=receiver.id,
                user_id=receiver.id,
                who_ids=[sender.id],
                source="request",
                request_id=request.id,
                recip_id=recipient.id,
            )
        )
        db.commit()
        assert db.get(Event, "e2").recip_id == recipient.id


def test_recipient_is_unique_per_request(client, family):
    _, _, group = family
    with SessionLocal() as db:
        sender, receiver = _users(db)[:2]
        request = EventRequest(
            group_id=group["id"], user_id=sender.id, title="청소", start_date=date(2026, 11, 3)
        )
        db.add(request)
        db.flush()
        for _ in range(2):
            db.add(
                EventRequestRecipient(
                    group_id=group["id"], user_id=receiver.id, request_id=request.id
                )
            )
        with pytest.raises(IntegrityError):
            db.flush()


def test_suggestion_defaults_and_event_link(client, family):
    _, _, group = family
    with SessionLocal() as db:
        user = _users(db)[0]
        suggestion = EventSuggestion(
            group_id=group["id"], user_id=user.id, title="치과", start_date=date(2026, 11, 5)
        )
        db.add(suggestion)
        db.flush()
        assert suggestion.status == SUGGESTION_PENDING
        assert suggestion.kind == KIND_APPOINTMENT
        assert suggestion.confirmed_at is None

        db.add(
            Event(
                id="e3",
                group_id=group["id"],
                title=suggestion.title,
                starts_at=datetime.now(UTC),
                created_by=user.id,
                user_id=user.id,
                suggestion_id=suggestion.id,
            )
        )
        db.commit()
        assert db.get(Event, "e3").suggestion_id == suggestion.id
