"""로그 소스 추상화.

adb 가 없는 머신에서도 뷰어 전체를 만들고 테스트하고 데모할 수 있어야 한다.
그래서 소스를 인터페이스 뒤로 뺀다: adb / 파일 재생 / 합성 생성기.
이 이음매는 로드맵의 `.session` 저장·재생이 필요로 하는 바로 그 이음매이기도 하다.
"""

from .base import LogSource
from .adb import AdbSource
from .filesrc import FileSource
from .synthetic import SyntheticSource

__all__ = ["LogSource", "AdbSource", "FileSource", "SyntheticSource", "build"]


def build(kind: str, **kw) -> LogSource:
    if kind == "adb":
        return AdbSource(**kw)
    if kind == "file":
        return FileSource(**kw)
    if kind in ("synth", "synthetic", "demo"):
        return SyntheticSource(**kw)
    raise ValueError(f"알 수 없는 소스: {kind} (adb|file|synth)")
