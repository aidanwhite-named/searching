"""
중앙 로깅 설정.
setup_logging()은 main.py / server.py 시작부에서 한 번만 호출한다.
"""

import logging
import sys

_FMT = "%(asctime)s.%(msecs)03d [%(levelname)-5s] [%(name)s] %(message)s"
_DATE = "%Y-%m-%d %H:%M:%S"

# 출력이 너무 많은 서드파티 로거 억제
_QUIET = [
    "httpx", "httpcore", "urllib3", "urllib",
    "sentence_transformers", "transformers",
    "torch", "huggingface_hub", "filelock",
    "qdrant_client", "grpc",
]


def setup_logging(level: str = "INFO", log_file: str | None = None) -> None:
    """루트 로거를 초기화한다. 중복 핸들러 방지 포함."""
    root = logging.getLogger()
    if root.handlers:
        return  # 이미 설정됨

    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = logging.Formatter(_FMT, datefmt=_DATE)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    if log_file:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)

    for name in _QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
