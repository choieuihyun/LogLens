"""adb logcat 소스.

핵심 결정 2가지:

* **`-v threadtime` 을 명시적으로 고정한다.** 포맷을 adb 기본값에 맡기면
  (사용자 환경/버전에 따라 달라진다) 파서가 조용히 깨진다. 우리가 못 박는다.
* **재연결은 여기서 끝낸다.** 기기 sleep / USB 재연결로 스트림이 끊기는 건
  예외 상황이 아니라 정상 동작이다. 상위 레이어가 이걸 몰라도 되게 한다.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import Iterator, List, Optional

from .base import LogSource, marker

# 파서가 아는 포맷. 바꾸려면 docs/RECORD_FORMAT.md §3 도 같이 바꿔야 한다.
LOGCAT_FORMAT = "threadtime"


class AdbSource(LogSource):
    name = "adb"

    def __init__(self, serial: Optional[str] = None, package: Optional[str] = None,
                 adb_path: str = "adb", clear_first: bool = False,
                 reconnect_delay: float = 2.0, dump: bool = False,
                 tail: Optional[int] = None):
        super().__init__()
        self.serial = serial
        self.package = package
        self.adb = adb_path
        self.clear_first = clear_first
        self.reconnect_delay = reconnect_delay
        # dump=True 면 `logcat -d` — 현재 링버퍼만 뱉고 끝낸다(재연결 없음).
        # config 자동 생성처럼 "지금 있는 것"만 필요할 때 쓴다.
        self.dump = dump
        # tail=N 이면 `-t N` — 버퍼의 **최근** N줄. 이게 없으면 가장 오래된 줄부터
        # 나와서, 표본을 앞에서 자를 때 부팅 직후 로그만 보게 된다. (실제로 당했다)
        self.tail = tail
        self.pid: Optional[int] = None
        self._proc: Optional[subprocess.Popen] = None

    # -- adb 호출 조립 --------------------------------------------------------
    def _base(self) -> List[str]:
        cmd = [self.adb]
        if self.serial:
            cmd += ["-s", self.serial]
        return cmd

    def _resolve_pid(self) -> Optional[int]:
        """대상 앱 pid 자동추적. 앱이 재시작되면 pid 가 바뀌므로 매 연결마다 다시 푼다."""
        if not self.package:
            return None
        try:
            out = subprocess.run(
                self._base() + ["shell", "pidof", self.package],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            return int(out.split()[0]) if out.split() else None
        except Exception:
            return None

    def available(self) -> bool:
        return shutil.which(self.adb) is not None

    def devices(self) -> List[str]:
        try:
            out = subprocess.run([self.adb, "devices"], capture_output=True,
                                 text=True, timeout=5).stdout
        except Exception:
            return []
        return [ln.split()[0] for ln in out.splitlines()[1:]
                if ln.strip() and ln.split()[-1] == "device"]

    # -- 스트림 ---------------------------------------------------------------
    def lines(self) -> Iterator[str]:
        if not self.available():
            yield marker(f"'{self.adb}' 를 PATH 에서 찾을 수 없습니다. "
                         f"--source file 또는 --source synth 를 쓰세요.")
            return

        while not self.stopped:
            devs = self.devices()
            if not devs:
                yield marker("연결된 기기 없음 — 대기 중")
                if self._wait():
                    return
                continue

            self.pid = self._resolve_pid()
            note = f"{self.serial or devs[0]} 연결됨"
            if self.package:
                note += f" / {self.package} pid={self.pid or '미실행'}"
            yield marker(note)

            try:
                yield from self._stream_once()
            except Exception as e:  # 스트림 예외로 뷰어가 죽으면 안 된다
                yield marker(f"스트림 오류: {type(e).__name__}: {e}")

            if self.stopped or self.dump:
                return
            yield marker("스트림 끊김 — 재연결 시도")
            if self._wait():
                return

    def _stream_once(self) -> Iterator[str]:
        if self.clear_first:
            subprocess.run(self._base() + ["logcat", "-c"],
                           capture_output=True, timeout=10)
        cmd = self._base() + ["logcat", "-v", LOGCAT_FORMAT]
        if self.tail:
            cmd += ["-t", str(self.tail)]     # -t 는 -d 를 함의한다
        elif self.dump:
            cmd += ["-d"]
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            if self.stopped:
                break
            yield line.rstrip("\n")
        self._terminate()

    def _wait(self) -> bool:
        """재연결 대기. stop 이 걸리면 True."""
        return self._stop.wait(self.reconnect_delay)

    def _terminate(self):
        p, self._proc = self._proc, None
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()

    def stop(self):
        super().stop()
        self._terminate()

    def describe(self) -> dict:
        return {"kind": self.name, "serial": self.serial,
                "package": self.package, "pid": self.pid,
                "format": LOGCAT_FORMAT, "dump": self.dump}
