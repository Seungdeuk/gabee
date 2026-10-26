"""일정 테이블의 정수 상수. 값이 DB 에 저장되므로 번호를 바꾸지 않는다."""

# events.kind, events_suggestions.kind
KIND_APPOINTMENT = 1  # 약속
KIND_TODO = 2  # 할 일

# events_suggestions.status
SUGGESTION_PENDING = 1  # 제안
SUGGESTION_CONFIRMED = 2  # 확정
SUGGESTION_DISMISSED = 3  # 버림

# events_request_recipients.status
RECIPIENT_WAITING = 1  # 대기
RECIPIENT_ACCEPTED = 2  # 수락
RECIPIENT_DECLINED = 3  # 어려움
