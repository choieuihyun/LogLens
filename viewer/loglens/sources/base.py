from __future__ import annotations

import threading
from typing import Iterator

# 소스가 상태 변화를 알릴 때 쓰는 마커. 파서는 이걸 RAW 로 흘려보내고,
# 서버는 raw 가 이 접두사로 시작하면 UI 상태줄로 올린다.
MARKER = "--------- loglens:"


def marker(text: str) -> str:
    return f"{MARKER} {text}"


class LogSource:
    """블로킹 제너레이터로 한 줄씩 뱉는다. 재연결은 소스가 스스로 책임진다."""

    name = "base"

    def __init__(self):
        self._stop = threading.Event()

    def lines(self) -> Iterator[str]:
        raise NotImplementedError

    def stop(self) -> None:
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def describe(self) -> dict:
        return {"kind": self.name}
