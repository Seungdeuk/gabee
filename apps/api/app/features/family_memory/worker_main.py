"""AI 추억 분석 워커의 별도 프로세스 진입점(PR4): `python -m app.features.family_memory.worker_main`.

모델은 **이 프로세스에서만** 올라간다(웹 프로세스는 인코더를 등록하지 않는다). 시작 조건(하나라도 아니면 아무것도 하지 않고 종료 코드 2):
`FAMILY_MEMORY_ENABLED=true`, `FAMILY_MEMORY_WORKER_ENABLED=true`, `FAMILY_MEMORY_ENCODER` 가 `siglip2`(또는 개발용 `fake`). 모델을 올리지 못하면 종료 코드 3(작업은
건드리지 않으므로 시도 횟수를 쓰지 않는다). 종료 신호(SIGINT·SIGTERM)를 받으면 루프를 멈추고 모델 자원을 정리한다. 진행 중이던 작업은 임대가 만료되면 되찾는다.
이 진입점은 어떤 사진도 자동으로 등록하지 않는다 — 큐에 들어 있는 작업만 처리한다."""

import logging
import signal
import sys

from app.shared.config import settings

from . import analysis, worker

logger = logging.getLogger(__name__)

EXIT_NOT_ENABLED = 2
EXIT_ENCODER_FAILED = 3


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if not (settings.family_memory_enabled and settings.family_memory_worker_enabled):
        logger.warning("family memory worker not enabled: nothing to do")
        return EXIT_NOT_ENABLED
    if (settings.family_memory_encoder or "off").lower() == "off":
        logger.warning("family memory encoder is off: nothing to do")
        return EXIT_NOT_ENABLED
    try:
        analysis.get_encoder()  # 시작할 때 한 번 올려 실패를 빨리 알린다(자원 사용량이 로그에 남는다)
    except Exception as exc:  # noqa: BLE001  내용이 로그에 남지 않게 종류만 적는다
        logger.error("family memory encoder load failed error=%s", type(exc).__name__)
        return EXIT_ENCODER_FAILED
    analysis.register_handlers()

    def _stop(*_: object) -> None:
        worker._stop.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    logger.info("family memory worker process started")
    try:
        worker._loop()
    finally:
        analysis.reset_encoder()  # 모델 자원 정리(GPU 캐시 포함)
    return 0


if __name__ == "__main__":
    sys.exit(main())
