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

# events_topics.color (schemas.TopicCreate.color 의 Literal 과 같은 목록)
TOPIC_COLORS = ("rose", "amber", "green", "sky", "purple")
DEFAULT_TOPIC_NAME = "경조사"  # 사람마다 처음 한 번 만들어 주는 기본 주제
DEFAULT_TOPIC_COLOR = "rose"

# 데일리 체크(events_check_items.kind)
CHECK_KIND_CHECK = 1  # 한 번 체크
CHECK_KIND_COUNT = 2  # 횟수 세기(하루 목표 숫자와 단위)
CHECK_GOAL_MAX = 9999  # 하루 목표 상한
CHECK_COUNT_MAX = 9999  # 오늘 횟수 상한(목표를 넘겨도 된다)
CHECK_REPEAT_ALL = "1111111"  # 반복 요일 기본값(월~일, 월=첫 글자)
CHECK_DAY_RANGE = 7  # 기록·조회 가능한 과거 날짜 범위(오늘부터 이 날짜 전까지)
NOTE_MAX = 100  # 날짜별 메모 글자 수 상한(서버). 앱 입력은 50자

# 응원(events_check_cheers.kind)
CHEER_LOVE = 1  # 사랑해요
CHEER_BEST = 2  # 최고예요
CHEER_WELL_DONE = 3  # 잘하셨어요

# 데일리 체크 추천 문구(events_check_suggestions.category)
SUGGEST_HABIT = 1  # 습관 추천
SUGGEST_CHEER = 2  # 응원 문구
