"""일반화 평가 사례(`gen_cases.py`) 5건의 가짜 대본(정상 대본: 올바른 행동). 가짜 모드와 **사전 점검**이 앱 경로를 끝까지 돌려 보는 데 쓴다.

사전 점검(`preflight`)은 실제 호출 없이 가짜 모델로 앱을 끝까지 돌려 요청 본문을 점검하므로, 사례마다 정상 대본이 있어야 한다.
공식 dev 대본(`dev_scripts.SCRIPTS`, 36건)과 섞지 않는다: `dev_scripts.scripts_for("dev", <dev 파일>)` 이 그 파일이 이 일반화 파일일 때만 이 모듈의 `SCRIPTS` 를 돌려준다.

정상 대본은 평가 기준이 의도한 행동 그대로다: 메인이 사용자가 말한 검색 범위와 주제를 지우지 않은 질문을 `ask_family_chat` 으로 넘기고,
소통 Agent 가 자기 가족방을 `search_messages` 로 찾은 뒤 다른 가족방은 볼 수 없다고 밝힌다. 실제 모델이 그렇게 하는지는 실모델 평가가 본다(대본의 통과는 연결이 된다는 뜻뿐이다).
"""

from . import gen_cases
from .fake_model import Script, call, say

PROMPT = "@가비 "
LIMIT = "우리 가족방에서는 {topic} 이야기를 찾지 못했어요. 다른 가족방은 검색할 수 없어요."


def _script(question: str, topic: str) -> Script:
    return {
        "main": [
            call("ask_family_chat", {"question": question.replace(PROMPT, "")}),
            say("(소통 Agent 의 답이 그대로 나가므로 쓰이지 않는다)"),
        ],
        "family_chat": [
            call("search_messages", {"query": topic}),
            say(LIMIT.format(topic=topic)),
        ],
    }


SCRIPTS: dict[str, Script] = {
    case_id: _script(question, topic) for case_id, question, topic in gen_cases.SPECS
}
