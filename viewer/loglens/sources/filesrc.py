"""파일 소스 — 저장된 로그 재생(replay) 또는 tail -f.

로드맵의 `.session` 저장/공유가 붙을 자리. 지금은 평문 로그 파일이 곧 세션이다.
"""

from __future__ import annotations

import pathlib
import time
from typing import Iterator

from .base import LogSource, marker


class FileSource(LogSource):
    name = "file"

    def __init__(self, path: str, follow: bool = False, delay: float = 0.0,
                 from_end: bool = False):
        super().__init__()
        self.path = pathlib.Path(path)
        self.follow = follow
        self.delay = delay          # 재생 속도: 줄당 초. 0이면 즉시 전부
        self.from_end = from_end

    def lines(self) -> Iterator[str]:
        if not self.path.exists():
            yield marker(f"파일 없음: {self.path}")
            return
        yield marker(f"재생: {self.path}")

        with self.path.open("r", encoding="utf-8", errors="replace") as fh:
            if self.from_end:
                fh.seek(0, 2)
            for line in fh:
                if self.stopped:
                    return
                yield line.rstrip("\n")
                if self.delay:
                    if self._stop.wait(self.delay):
                        return

            if not self.follow:
                yield marker("재생 완료")
                return

            yield marker("tail 모드 — 추가되는 줄을 기다립니다")
            while not self.stopped:
                line = fh.readline()
                if line:
                    yield line.rstrip("\n")
                else:
                    if self._stop.wait(0.25):
                        return

    def describe(self) -> dict:
        return {"kind": self.name, "path": str(self.path),
                "follow": self.follow, "delay": self.delay}
