"""돌봄 기능 설정: 기본 체크 항목, 추천 문구, 식단 메뉴 템플릿. 문구·메뉴는 코드 수정 없이 여기서 바꾼다."""

# 처음 열 때 만들어 두는 샘플 항목 7개 (화면에 보이는 순서).
# rule_key 는 추천 규칙이 어느 항목을 볼지 정한다. meal_type 은 식단 추천이 어느 끼니인지 정한다.
SAMPLE_ITEMS = (
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

# 위치 확인은 아직 실제 GPS 를 쓰지 않는다. 항상 같은 예시 위치를 돌려준다.
EXAMPLE_LOCATION = {
    "place": "집 근처 공원 (예시)",
    "lat": 37.5665,
    "lng": 126.9780,
    "notice": "예시 위치예요. 실제 GPS 가 아니에요.",
}
