"""알림함 공용 모델(app/shared/notifications.py) 시험: 스키마 등록과 테이블 생성."""

from app.shared.db import SessionLocal
from app.shared.notifications import KINDS, PUSH_KINDS, Notification
from app.shared.schema import feature_tables


def test_schema_registered_and_kinds():
    tables = feature_tables()
    assert "notifications" in tables
    assert "notifications" in tables["notifications"]
    assert KINDS == ("schedule", "billing", "family_group", "support")
    assert PUSH_KINDS == (*KINDS, "chat")  # 소통은 푸시 설정에서만 끌 수 있고 알림함 분류는 아니다


def test_create_all_creates_columns(client, family):
    a, _b, group = family
    me = client.get("/family-group/me", headers=a).json()
    with SessionLocal() as db:
        row = Notification(
            user_id=me["id"],
            group_id=group["id"],
            kind="family_group",
            event="join_requested",
            title="가족 그룹 참여 요청이 왔어요",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        assert len(row.id) == 12
        assert row.created_at is not None
        assert row.read_at is None
        assert row.body is None
