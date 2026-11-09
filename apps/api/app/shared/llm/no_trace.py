"""랭체인·랭그래프 추적(LangSmith)을 끈 채로 돌리는 도구.

환경변수(`LANGSMITH_TRACING=true`, `LANGCHAIN_TRACING_V2=true` 등) 하나로 추적이 켜지면 질문·도구 결과·답이 외부 서비스로 나간다.
`LANGSMITH_TRACING=false` 만으로는 `LANGCHAIN_TRACING_V2=true` 가 같이 있을 때 꺼지지 않으므로, 환경과 상관없이
`langsmith.tracing_context(enabled=False)` 로 감싼다. 이 문맥은 ContextVar 라서 안쪽에서 도는 하위 그래프·체인도 함께 꺼지고,
호출 방식·스레드·다른 ContextVar 는 바꾸지 않는다. `langsmith` 는 `langchain-core` 가 함께 설치한다."""

from langsmith.run_helpers import tracing_context


def no_trace():
    """`with no_trace():` 안에서 부르는 랭체인 Runnable·랭그래프는 추적 이벤트를 만들지 않는다."""
    return tracing_context(enabled=False)
