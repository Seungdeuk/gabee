"""챗봇 에이전트의 도구(랭체인 도구). 각 기능이 shared/admin_facts 명단에 올린 숫자 함수를 도구로 바꾼다.

숫자를 늘리려면 이 파일이 아니라 그 기능 폴더의 admin_facts.py 에서 register() 한다.
외부(Claude)로 나가는 글이므로 개수와 오류 종류만 담는 규칙은 명단에 올리는 쪽이 지킨다.
"""

from langchain_core.tools import StructuredTool
from sqlalchemy.orm import Session

from app.shared.admin_facts import Fact, all_facts

UNKNOWN = "확인할 수 없음"


def _tool(db: Session, fact: Fact) -> StructuredTool:
    def read(**args) -> str:
        """한 도구를 못 읽어도 다른 도구로 답할 수 있게 실패는 글로 돌려준다."""
        try:
            return "\n".join(fact.read(db, **args))
        except Exception:  # noqa: BLE001  표가 없거나 조회 실패. 내용은 남기지 않는다
            db.rollback()
            return UNKNOWN

    if fact.params is None:
        # 입력 없는 도구. 빈 괄호 함수를 넘겨야 Claude 에게 입력칸이 안 보인다
        def run() -> str:
            return read()

        tool = StructuredTool.from_function(func=run, name=fact.name, description=fact.description)
    else:

        def run_with(**args) -> str:  # Claude 가 채운 입력칸(args_schema 로 검사된 값)을 넘긴다
            return read(**args)

        tool = StructuredTool.from_function(
            func=run_with, name=fact.name, description=fact.description, args_schema=fact.params
        )
    # 답변 단계 화면에 보일 말(label). metadata 는 Claude 에게 보내는 도구 정의(spec)에 들어가지 않는다
    tool.metadata = {"label": fact.label}
    return tool


def tools(db: Session) -> list[StructuredTool]:
    return [_tool(db, fact) for fact in all_facts()]
