"""L2 실행기 진입점: `cd apps/api && python -m evals.agent_eval.run [--dry-run | --fake | --real --approve-usd N]`.

논리는 `cli.py` 에 있다. 이 파일은 `app` 을 불러오지 않고 `cli.main` 만 부른다(환경변수를 정한 뒤에 앱을 불러오기 위해서다).
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
