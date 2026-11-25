"""미검출 원인 분류(결정론적). 검색 결과 모양만 보고 정하고 모델·확률을 쓰지 않는다.

원인(`CAUSES`)
- query_selection: 질문에는 맞는 글이 있지만 이 검색어의 낱말이 gold 글에 모두 들어 있지 않다. 이상적인 검색어(ideal)로는 gold 가 검색 범위(200건) 안에 나온다.
  에이전트가 검색어를 잘못 고른 경우(검색기 결함이 아니다).
- keyword_limitation: 질문의 개념어가 gold 글에 없다(동의어·간접 표현, `lexical_gap`). 글자 일치 검색의 구조적 한계이고 기능 결함과 구분한다.
- result_limit: 검색어가 맞아 gold 가 내부 진단(200건)에서는 나오지만 상위 10건(도구 기본 한도)에 들지 못했다. 최신순이라 오래된 글이 밀린다.
- message_content: gold 글에 검색어가 없고 이상적인 검색어로도 닿지 않는다(메시지 내용 문제). 평가셋 오류 후보라 보고서에서 따로 본다.
- content_not_indexed: 글자(text)에 내용이 색인되지 않는 글(카드). 키워드 검색이 원리상 찾지 못한다(동의어 문제가 아니다).
- context_needed: 대화 맥락(history)이 있어야 검색어가 정해지는 질문을 맥락 없이 검색했다.
- scope: 범위 밖 글이 나왔다(별도 하드 실패이며 미검출 원인과는 따로 센다).
"""

CAUSES = (
    "query_selection",
    "keyword_limitation",
    "result_limit",
    "message_content",
    "content_not_indexed",
    "context_needed",
)


def classify_miss(
    *,
    gold_key: str,
    query_set: str,
    in_deep: bool,
    in_ideal_deep: bool,
    card_keys: set[str],
    lexical_gap: bool,
    needs_history: bool,
) -> str:
    """gold 한 건이 상위 10건에 없을 때의 원인. 순서가 곧 우선순위다.

    - in_deep: 이 검색어의 200건 내부 진단에 gold 가 있는가.
    - in_ideal_deep: 같은 사례의 이상적인 검색어(ideal) 200건 진단에 gold 가 있는가.
    - card_keys: 내용이 text 에 색인되지 않는 카드 메시지 키."""
    if gold_key in card_keys:
        return "content_not_indexed"
    if query_set == "no_history" and needs_history:
        return "context_needed"
    if in_deep:
        return "result_limit"
    if lexical_gap:
        return "keyword_limitation"
    if query_set != "ideal" and in_ideal_deep:
        return "query_selection"
    return "message_content"
