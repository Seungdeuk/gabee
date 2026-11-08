"""평가에서 LLM 을 부르는 횟수의 상한 계산. 실제로 부르기 전에 예상 횟수를 먼저 보여 주고 상한을 넘으면 멈춘다.

  질문 생성 = ceil(조각 수 × 조각당 질문 수 ÷ 한 번에 만드는 질문 수)
  답변      = 질문 수 × 반복 횟수
  judge     = 답변 수 (항목을 나눠 채점하면 × 항목 수)
  루프      = (위 합계) × 반복 횟수

여기서 센 것은 '이 스크립트가 보내는 요청 수'다. 에이전트는 한 답변을 만들 때 도구를 부르며 모델을 최대 4번까지 다시 부르므로
(shared/llm/agent.py max_steps) 실제 모델 호출 수는 답변 수의 1~4배가 될 수 있다."""

import math
import sys


def question_gen_calls(chunks: int, per_chunk: int, batch: int) -> int:
    """질문 생성 요청 수. batch 는 요청 한 번에 만드는 질문 수."""
    if min(chunks, per_chunk) < 0 or batch < 1:
        raise ValueError(
            "조각 수·조각당 질문 수는 0 이상, 한 번에 만드는 질문 수는 1 이상이어야 해요"
        )
    return math.ceil(chunks * per_chunk / batch)


def answer_calls(questions: int, repeats: int) -> int:
    return questions * max(repeats, 0)


def judge_calls(answers: int, items: int = 1) -> int:
    """items: 항목을 나눠 채점하면 항목 수, 한 번에 모두 채점하면 1."""
    return answers * max(items, 1)


def loop_calls(per_round: int, rounds: int) -> int:
    return per_round * max(rounds, 0)


def total(*parts: int) -> int:
    return sum(parts)


def guard(label: str, needed: int, limit: int | None) -> None:
    """예상 횟수를 출력하고 상한(limit)을 넘으면 종료한다. limit 이 None 이면 상한 없이 실행한다고 알린다."""
    cap = "상한 없음" if limit is None else f"상한 {limit}회"
    print(f"[호출 예상] {label}: {needed}회 ({cap})")
    if limit is not None and needed > limit:
        print(f"예상 {needed}회가 상한 {limit}회를 넘어서 실행하지 않아요.", file=sys.stderr)
        raise SystemExit(2)
