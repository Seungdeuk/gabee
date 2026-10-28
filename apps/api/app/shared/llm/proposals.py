"""에이전트가 '제안'한 쓰기 동작. 에이전트는 DB 를 바꾸지 못하고, 사용자가 확인 버튼을 눌러야 실행된다.

제안은 서버가 서명한 토큰(JWT, 10분)이다. 토큰에는 동작 이름·검증된 인자·사용자·가족 그룹이 들어 있어서
다른 사람이나 다른 가족이 쓸 수 없고, 로그인용 Access Token 으로는 통하지 않는다(aud·token_use 가 다름).
사용자에게 보여 주는 요약문은 LLM 이 쓴 글이 아니라 서버가 검증된 인자로 만든 문장이다.

한 번 실행한 토큰의 기록(jti)은 DB(`agent_proposal_uses`)에 두어 서버 인스턴스가 여러 개이거나 재시작해도 같은 토큰을 다시 쓸 수 없다.
기록을 남긴 뒤(커밋) 실행하므로, 그 사이에 서버가 죽으면 토큰은 소진된다(두 번 실행되는 것보다 안전한 쪽)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.shared import tokens
from app.shared.config import settings
from app.shared.errors import ApiError
from app.shared.used_proposals import AgentProposalUse

AUDIENCE = "gabee-agent-action"
TOKEN_USE = "agent_action"
TTL = timedelta(minutes=10)
MAX_PER_ANSWER = 3  # 한 답변에서 제안할 수 있는 동작 수


@dataclass
class Proposal:
    token: str
    summary: str
    tab: str  # 확인 요청을 보낼 탭: billing | care
    key: str = (
        ""  # 같은 대상의 제안을 가려내는 값(같은 답변에서 고쳐 낸 제안이 앞선 것을 대신하게 한다)
    )


def add(
    proposed: list,
    tab: str,
    action: str,
    args: dict,
    summary: str,
    user_id: str,
    group_id: str,
    key: str,
) -> Proposal:
    """제안을 만들어 목록에 넣는다. 같은 답변에서 같은 대상(key)을 다시 제안하면 앞선 제안은 목록에서 빼서,
    잘못 낸 제안이 확인 버튼으로 남지 않게 한다(빠진 토큰은 사용자에게 가지 않는다)."""
    proposed[:] = [p for p in proposed if p.key != key]
    made = create(tab, action, args, summary, user_id, group_id)
    made.key = key
    proposed.append(made)
    return made


def create(
    tab: str, action: str, args: dict, summary: str, user_id: str, group_id: str
) -> Proposal:
    now = datetime.now(UTC)
    claims = {
        "iss": settings.jwt_issuer,
        "aud": AUDIENCE,
        "sub": user_id,
        "iat": now,
        "exp": now + TTL,
        "jti": uuid.uuid4().hex,
        "token_use": TOKEN_USE,
        "tab": tab,
        "grp": group_id,
        "act": action,
        "args": args,
        "summary": summary,
    }
    return Proposal(jwt.encode(claims, tokens._secret(), algorithm=tokens.ALGORITHM), summary, tab)


def _invalid() -> ApiError:
    return ApiError(400, "proposal_invalid", "확인할 수 없는 요청이에요. 다시 시도해 주세요")


def consume(db: Session, token: str, tab: str, user_id: str, group_id: str) -> dict:
    """토큰을 검증하고 한 번만 쓰게 표시(DB 에 기록·커밋)한 뒤 {act, args, summary} 를 돌려준다."""
    try:
        claims = jwt.decode(
            token,
            tokens._secret(),
            algorithms=[tokens.ALGORITHM],
            audience=AUDIENCE,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "jti", "sub", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError:
        raise ApiError(
            400, "proposal_expired", "요청한 지 너무 오래 지났어요. 다시 말씀해 주세요"
        ) from None
    except jwt.InvalidTokenError:
        raise _invalid() from None
    if (
        claims.get("token_use") != TOKEN_USE
        or claims.get("tab") != tab
        or claims.get("sub") != user_id
        or claims.get("grp") != group_id
    ):
        raise _invalid()
    expires_at = datetime.fromtimestamp(float(claims["exp"]), UTC)
    db.execute(delete(AgentProposalUse).where(AgentProposalUse.expires_at <= datetime.now(UTC)))
    db.add(AgentProposalUse(jti=claims["jti"], expires_at=expires_at))
    try:
        db.commit()  # 기본키(jti) 충돌이 곧 재사용이다. 여러 인스턴스가 동시에 써도 한쪽만 성공한다
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "proposal_used", "이미 처리한 요청이에요") from None
    return {
        "act": claims["act"],
        "args": claims["args"],
        "summary": claims["summary"],
        "jti": claims["jti"],
    }


def release(db: Session, jti: str) -> None:
    """실행에 실패했을 때 토큰을 다시 쓸 수 있게 되돌린다(만료 전까지)."""
    db.rollback()  # 실패한 실행이 남긴 트랜잭션을 먼저 정리한다
    db.execute(delete(AgentProposalUse).where(AgentProposalUse.jti == jti))
    db.commit()


def reset() -> None:
    """시험용: 사용 기록을 모두 지운다."""
    from app.shared.db import SessionLocal

    with SessionLocal() as db:
        db.execute(delete(AgentProposalUse))
        db.commit()
