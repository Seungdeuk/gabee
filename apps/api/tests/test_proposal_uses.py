"""에이전트 제안 토큰의 사용 기록(agent_proposal_uses): DB 에 있어서 서버 인스턴스가 달라도·재시작해도 한 번만 쓸 수 있다."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.shared.db import SessionLocal
from app.shared.errors import ApiError
from app.shared.llm import proposals
from app.shared.used_proposals import AgentProposalUse


def _token(user_id="u1", group_id="g1", tab="billing"):
    return proposals.create(tab, "add_expense", {"title": "치과"}, "치과", user_id, group_id).token


@pytest.fixture(autouse=True)
def _clean(client):  # client 가 임시 DB 테이블을 만든다
    proposals.reset()


def _consume(token, tab="billing", user_id="u1", group_id="g1"):
    with SessionLocal() as db:  # 요청마다 새 세션: 다른 인스턴스·재시작을 흉내 낸다
        return proposals.consume(db, token, tab, user_id, group_id)


def test_token_can_be_used_only_once_across_sessions():
    token = _token()
    assert _consume(token)["act"] == "add_expense"
    with pytest.raises(ApiError) as e:
        _consume(token)
    assert (e.value.status, e.value.code) == (409, "proposal_used")


def test_only_the_jti_is_stored_not_the_token():
    token = _token()
    claims = _consume(token)
    with SessionLocal() as db:
        rows = db.scalars(select(AgentProposalUse)).all()
    assert [r.jti for r in rows] == [claims["jti"]]
    assert token not in repr(rows[0].__dict__)


def test_release_allows_reuse_after_a_failed_execute():
    token = _token()
    claims = _consume(token)
    with SessionLocal() as db:
        proposals.release(db, claims["jti"])
    assert _consume(token)["jti"] == claims["jti"]


def test_wrong_user_group_or_tab_does_not_burn_the_token():
    token = _token()
    for kwargs in ({"user_id": "u2"}, {"group_id": "g2"}, {"tab": "care"}):
        with pytest.raises(ApiError) as e:
            _consume(token, **kwargs)
        assert e.value.code == "proposal_invalid"
    assert _consume(token)["act"] == "add_expense"  # 본인이 쓰면 아직 쓸 수 있다


def test_expired_records_are_cleaned_when_a_new_token_is_used():
    with SessionLocal() as db:
        db.add(AgentProposalUse(jti="old", expires_at=datetime.now(UTC) - timedelta(minutes=1)))
        db.commit()
    _consume(_token())
    with SessionLocal() as db:
        assert "old" not in {r.jti for r in db.scalars(select(AgentProposalUse))}
