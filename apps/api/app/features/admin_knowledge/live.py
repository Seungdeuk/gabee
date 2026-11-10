"""챗봇이 쓸 지금 숫자. 관리자 화면이 쓰는 조회 함수를 그대로 불러서 화면과 숫자가 같다.

외부(Claude)로 나가는 글이므로 개수와 오류 종류만 칸을 골라 담는다.
이름·이메일·사용자 id 가 든 rows, 오류 message, trace id 는 쓰지 않는다. 칸을 늘릴 때도 이 규칙을 지킨다.
"""

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.features.ops_admin import query_service
from app.features.service_admin import service as service_admin

RANGE = "24h"
RECENT_ERRORS = 5
UNKNOWN = "확인할 수 없음"


def _members(db: Session) -> list[str]:
    m = service_admin.members(db)
    return [
        f"전체 회원: {m.total}명",
        f"이번 주 가입: {m.joined_this_week}명",
        f"최근 7일 활성 사용자: {m.active_7d}명",
        f"가족 없는 회원: {m.no_family}명",
        f"이메일 인증 회원: {m.email_verified}명",
    ]


def _groups(db: Session) -> list[str]:
    g = service_admin.groups(db)
    return [
        f"가족 그룹: {g.total}개",
        f"구성원이 1명뿐인 가족: {g.single_member}곳",
        f"승인 대기 참가 요청: {g.pending_total}건",
        f"AI 를 켠 가족: {g.ai_enabled}곳",
    ]


def _support(db: Session) -> list[str]:
    s = service_admin.support(db)
    return [
        f"문의·신고: 새 문의 {s.new}건, 처리 중 {s.working}건, 답변 완료 {s.done}건, 신고 {s.reports}건"
    ]


def _ai(db: Session) -> list[str]:
    a = service_admin.ai_usage(db)
    return [f"AI 요청: 오늘 {a.today}회, 최근 7일 {a.week}회, 최근 30일 {a.month}회"]


def _requests(db: Session) -> list[str]:
    o = query_service.summary(db, RANGE)
    if not o.metrics_enabled:  # 꺼져 있으면 0 은 진짜 0 이 아니다
        return ["서버 요청 지표: 수집이 꺼져 있어 알 수 없음"]
    return [
        f"최근 24시간 요청: {o.requests}건",
        f"최근 24시간 5xx 오류: {o.errors_5xx}건, 4xx: {o.errors_4xx}건, 오류율 {o.error_rate:.2%}",
        f"최근 24시간 평균 응답: {o.avg_ms:.0f}ms",
    ]


def _errors(db: Session) -> list[str]:
    e = query_service.errors(db, RANGE, None, RECENT_ERRORS)
    if not e.errors_enabled:
        return ["오류 이벤트: 수집이 꺼져 있어 알 수 없음"]
    if not e.items:
        return ["최근 24시간 기록된 오류: 없음"]
    return [
        f"최근 24시간 오류: {i.event_type}, {i.method} {i.route}, {i.status}, {i.occurrences}회, {i.kind}"
        for i in e.items
    ]


SECTIONS: tuple[tuple[str, Callable[[Session], list[str]]], ...] = (
    ("회원", _members),
    ("가족", _groups),
    ("문의", _support),
    ("AI", _ai),
    ("서버 요청", _requests),
    ("오류", _errors),
)


def live_summary(db: Session) -> str:
    """한 칸을 못 읽어도 나머지로 답할 수 있게 칸마다 따로 읽는다."""
    lines: list[str] = []
    for name, read in SECTIONS:
        try:
            lines.extend(read(db))
        except Exception:  # noqa: BLE001  표가 없거나 조회 실패. 내용은 남기지 않는다
            db.rollback()
            lines.append(f"{name}: {UNKNOWN}")
    return "\n".join(lines)
