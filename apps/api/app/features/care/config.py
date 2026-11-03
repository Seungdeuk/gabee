"""돌봄 기능 설정: 위치 공유 정책(지금은 보류). 데일리 체크 기본 항목·추천·식단 메뉴는 지웠다."""

# 위치 공유 정책. 동의한 사람의 위치만 받고, 가족 구성원만 볼 수 있다.
LOCATION_RETENTION_DAYS = 7  # 이보다 오래된 위치는 지운다
LOCATION_MAX_POINTS = 50  # 한 번에 보낼 수 있는 위치 개수
LOCATION_FUTURE_SKEW_MINUTES = 5  # 기기 시계 오차로 이만큼 미래인 시각까지는 받는다
