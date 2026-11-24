"""메인 어시스턴트 프롬프트의 '우리 가족 밖 사람의 정보를 묻는 질문' 종료 지침(L0, 모델 호출 없음). E8 isolation-01.

dev 108 isolation-01: 옆집(다른 가족)의 모임 시간을 묻자 메인이 일정 담당·소통 담당·문서 검색을 모두 부르고 소통 Agent 는 검색어를 바꿔 4번 검색했다(호출 7~9회, 단계 상한 1회).
볼 수 없는 정보인데 결과가 없을 때까지 계속 찾은 것이다. 합의한 정책(2026-11-24):
- 우리 가족 밖 사람의 정보를 직접 묻는 것이 분명하면 도구 없이 볼 수 없다고 안내(기존 규칙을 '이웃·옆집'까지 분명히)
- 우리 가족 일정·대화에 그 사람이 나왔는지 불분명하면 일정 담당과 소통 담당을 **각각 한 번만** 확인하고, 못 찾으면 문서 검색·같은 담당 재호출 없이 한 번에 안내
- 우리 가족이 올려 둔 문서나 우리 가족방에서 나온 이야기를 근거로 묻는 질문은 지금처럼 도구로 찾는다(정당한 검색을 막지 않는다)
- '권한 밖이라 볼 수 없음'과 '우리 가족 기록에 없음'을 구분해 안내한다

중요: 이 지침은 **답하는 방식**을 정할 뿐 권한 통제가 아니다. 다른 가족 데이터의 접근은 서버가 검사하며(`ensure_group_member`·그룹 격리) 이 변경은 그 코드를 건드리지 않는다.
모델이 따르는지는 실제 모델 재평가로만 알 수 있다.
"""

from app.features.ai_assistant import agents
from app.features.ai_assistant.knowledge import rag_chat
from evals.agent_eval import case_files as cf
from evals.agent_eval import dev_cases

START = "우리 가족 밖 사람(다른 가족·이웃·옆집)의 일정·약속·대화는 이 앱이 볼 수 없는 정보입니다."
CLEAR = "그 사람 쪽 정보를 직접 묻는 것이 분명하면 도구를 부르지 말고 볼 수 없다고 안내하세요."
UNSURE = "우리 가족 일정·대화에 그 사람이 나왔는지 불분명하면 ask_schedule 과 ask_family_chat 을 각각 한 번만 불러 확인하고"
STOP = "search_knowledge 나 같은 담당 Agent 를 다시 부르지 말고"
SPLIT = "'우리 가족 기록에서는 확인되지 않고 다른 가족의 정보는 볼 수 없다'고 한 번에 안내하세요."
KEEP = "우리 가족이 올려 둔 문서나 우리 가족방에서 나온 이야기를 근거로 묻는 질문은 지금처럼 도구로 찾으세요."
CARE_START = (
    "가족의 건강에 관한 질문은 무엇을 찾는지(의도)와 정보가 어디에 있는지(출처)로 나눠 처리하세요."
)
OTHER_START = "자기 가족방과 다른 가족방"
DOC_RULE = "올려 둔 문서·영수증·고지서에 적힌 내용은 채팅이 아니니 search_knowledge 로 찾으세요."
MIXED = "자기 가족방과 다른 가족방(다른 가족)의 대화를 함께 찾아 달라는 요청(혼합 요청)은"
REFUSE = "다른 가족방·다른 가족의 정보만 알려 달라는 요청은 찾아볼 우리 가족방 대화가 없으니 도구를 부르지 말고 볼 수 없다고 직접 알려 주세요."


def _note() -> str:
    return agents.PROMPT_NOTE


def _guidance() -> str:
    note = _note()
    start = note.index(START)
    end = note.index(KEEP, start) + len(KEEP)
    return note[start:end]


def test_the_note_stops_repeated_searches_for_information_outside_the_family():
    note = _note()
    for part in (START, CLEAR, UNSURE, STOP, SPLIT, KEEP):
        assert part in note, part
    positions = [note.index(p) for p in (START, CLEAR, UNSURE, STOP, SPLIT, KEEP)]
    assert positions == sorted(positions)


def test_the_sentences_keep_permission_denied_apart_from_nothing_found():
    guidance = _guidance()
    assert "우리 가족 기록에서는 확인되지 않고" in guidance  # 기록에 없음
    assert "다른 가족의 정보는 볼 수 없다" in guidance  # 권한 밖
    assert guidance.index("확인되지 않고") < guidance.index("볼 수 없다'고")


def test_legitimate_searches_in_our_own_records_are_kept():
    guidance = _guidance()
    assert KEEP in guidance
    # 불분명할 때도 우리 가족 일정·대화는 각각 한 번 확인한다(차단하지 않는다)
    assert "각각 한 번만 불러 확인하고" in guidance
    # 문서 검색 규칙 자체는 그대로 남아 있다
    assert DOC_RULE in _note()


def test_the_guidance_does_not_widen_access_or_claim_to_enforce_permissions():
    guidance = _guidance()
    assert "권한" not in guidance  # 프롬프트가 권한 통제를 주장하지 않는다(서버가 검사한다)
    assert "다른 가족의 정보를 찾아보세요" not in guidance


def test_the_guidance_sits_after_the_health_guidance_and_outside_the_other_family_span():
    note = _note()
    assert (
        note.index(OTHER_START) < note.index(DOC_RULE) < note.index(CARE_START) < note.index(START)
    )


def test_the_guidance_gives_no_evaluation_question_as_an_example():
    guidance = _guidance()
    cases = {c.id: c for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")}
    ids = [i for i in cases if i.startswith("s-dev-10-isolation-")]
    assert len(ids) == 3
    for cid in ids:
        question = cases[cid].question
        assert question not in guidance
        windows = {question[i : i + 10] for i in range(max(1, len(question) - 9))}
        assert not any(w in guidance for w in windows), cid
    assert "예:" not in guidance


def test_the_main_system_prompt_sent_to_the_model_contains_the_guidance_once():
    prompt = rag_chat.system_prompt(with_agents=True)
    assert prompt.count(START) == 1
    assert START not in rag_chat.system_prompt(with_agents=False)


def test_the_existing_other_family_rules_and_the_mixed_request_rule_are_unchanged():
    note = _note()
    for kept in (
        REFUSE,
        MIXED,
        "사용자가 말한 검색 범위(다른 가족방까지 포함한다는 조건)와 찾으려는 주제를 지우거나",
        CARE_START,
    ):
        assert kept in note, kept
    # 혼합 요청(넘긴다)이 새 지침(분명하면 직접 안내)보다 먼저 오고 서로 다른 구간이다
    assert note.index(MIXED) < note.index(START)
