"""푸시 토큰·푸시 설정 테이블이 알림 기능의 스키마 점검 대상으로 등록돼 있는지."""

from app.shared.schema import feature_tables


def test_push_tables_registered_to_notifications_feature():
    tables = feature_tables()["notifications"]
    assert {"notifications", "push_tokens", "push_settings"} <= set(tables)
