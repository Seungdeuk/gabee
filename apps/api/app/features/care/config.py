"""돌봄 기능 설정: 기본 체크 항목, 추천 문구, 식단 메뉴 템플릿. 문구·메뉴는 코드 수정 없이 여기서 바꾼다."""

# 새 가족이 처음 열 때 만들어 주는 항목(화면에 보이는 순서): 매일 한 번 누르는 체크만 둔다. 수치·컨디션 같은 항목은 사용자가 "항목 추가"에서 직접 만든다.
# rule_key 는 추천 규칙이 어느 항목을 볼지 정한다(그 항목이 없으면 그 추천은 나오지 않는다). meal_type 은 식단 추천이 어느 끼니인지 정한다.
# 이미 항목이 있는 가족에게는 아무것도 바꾸지 않는다.
SAMPLE_ITEMS = (
    {"name": "아침 식사", "mode": "yesno", "time": "08:00", "meal_type": "breakfast"},
    {"name": "영양제", "mode": "yesno", "time": "09:00", "rule_key": "supplement"},
    {"name": "점심 식사", "mode": "yesno", "time": "12:00", "meal_type": "lunch"},
    {"name": "저녁 식사", "mode": "yesno", "time": "19:00", "meal_type": "dinner"},
)

# 예전 기본 항목 7개(컨디션·물·산책 포함). 추천 규칙(water·walk·condition)과 수치·컨디션 기록 방식을 시험하는 데 쓴다.
# 서비스는 이 목록을 쓰지 않는다 — 시험과 평가셋이 SAMPLE_ITEMS 를 이것으로 바꿔서 쓴다.
FULL_SAMPLE_ITEMS = (
    {"name": "아침 식사", "mode": "yesno", "time": "08:00", "meal_type": "breakfast"},
    {"name": "영양제", "mode": "yesno", "time": "09:00", "rule_key": "supplement"},
    {"name": "컨디션", "mode": "condition", "time": "10:00", "rule_key": "condition"},
    {"name": "점심 식사", "mode": "yesno", "time": "12:00", "meal_type": "lunch"},
    {
        "name": "물",
        "mode": "number",
        "unit": "ml",
        "target": 1500,
        "time": "18:00",
        "rule_key": "water",
    },
    {
        "name": "산책",
        "mode": "number",
        "unit": "분",
        "target": 30,
        "time": "17:00",
        "rule_key": "walk",
    },
    {"name": "저녁 식사", "mode": "yesno", "time": "19:00", "meal_type": "dinner"},
)

MISSING_GRACE_MINUTES = 60  # 예정 시각 + 이 시간이 지나도 완료되지 않으면 누락

# 규칙 기반 추천 문구. {left}, {target}, {unit} 은 서비스가 채운다.
RECOMMENDATIONS = {
    "water_none": "오늘 물 기록이 아직 없어요. 따뜻한 물 한 잔부터 권해 보세요.",
    "water_low": "물을 {left}{unit} 더 마시면 목표({target}{unit})예요. 한 잔 권해 보세요.",
    "walk_none": "오늘 산책 기록이 아직 없어요. 날씨가 괜찮다면 가볍게 걸어 보시라고 말씀드려 보세요.",
    "walk_low": "산책을 {left}{unit} 더 하면 목표({target}{unit})예요. 짧게라도 걸어 보세요.",
    "condition_bad": "컨디션이 나쁘다고 기록됐어요. 전화로 안부를 확인하고, 계속되면 병원 상담을 권해 보세요.",
    "condition_none": "오늘 컨디션이 아직 기록되지 않았어요. 안부를 물어봐 주세요.",
    "supplement": "영양제를 아직 챙겨 드시지 않았어요. 잊지 않도록 알려 주세요.",
    "none": "오늘은 추가로 챙길 것이 없어요.",
}

MEAL_LABELS = {"breakfast": "아침", "lunch": "점심", "dinner": "저녁"}

# 끼니별 메뉴 템플릿. "다른 메뉴"를 누를 때마다 순서대로 돈다.
MEAL_MENUS = {
    "breakfast": ["야채죽", "계란찜과 밥", "두부 된장국", "바나나와 요거트", "고구마와 우유"],
    "lunch": ["비빔밥", "닭죽", "생선구이 정식", "잔치국수", "순두부찌개"],
    "dinner": ["미역국과 밥", "두부조림 정식", "채소 볶음밥", "북엇국", "된장찌개 정식"],
}

# 위치 공유 정책. 동의한 사람의 위치만 받고, 가족 구성원만 볼 수 있다.
LOCATION_RETENTION_DAYS = 7  # 이보다 오래된 위치는 지운다
LOCATION_MAX_POINTS = 50  # 한 번에 보낼 수 있는 위치 개수
LOCATION_FUTURE_SKEW_MINUTES = 5  # 기기 시계 오차로 이만큼 미래인 시각까지는 받는다
