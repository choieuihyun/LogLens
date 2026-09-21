"""합성 소스 — 기기 없이 뷰어 전체를 돌리는 데모 생성기.

기기/adb 없이도 `loglens --source synth` 하나로 탭·이슈트레이·대시보드가
전부 살아 있는 화면을 보여준다. README 의 GIF 를 이걸로 찍는다.

의도적으로 섞어 넣는 것들:
  - 성공/실패가 섞인 도메인 트래픽 (성공률 차트가 의미를 갖도록)
  - flowId 로 이어지는 로그인 퍼널 (중간 이탈 포함)
  - 레거시 자유형식 로그 (점진 도입 시나리오)
  - 크래시 스택 / ANR (이슈 트레이)
"""

from __future__ import annotations

import itertools
import random
import time
from datetime import datetime
from typing import Iterator, List

from .base import LogSource, marker

PID = 4321

LOGIN_FUNNEL = ["LOGIN_START", "CREDENTIAL_CHECK", "TOKEN_ISSUE", "PROFILE_FETCH", "LOGIN_OK"]

# 조직도 같은 계층 화면. (부모, 자식들) — 사용자가 펼친 것만 로그가 남는 걸 흉내낸다.
ORG_TREE = {
    None:   [("N1", "본사")],
    "N1":   [("N11", "연구소"), ("N12", "영업본부")],
    "N11":  [("N111", "플랫폼팀"), ("N112", "앱개발팀")],
    "N112": [("N1121", "안드로이드"), ("N1122", "iOS")],
    "N12":  [("N121", "국내영업"), ("N122", "해외영업")],
}

CRASH_STACK = [
    ("E", "AndroidRuntime", "FATAL EXCEPTION: main"),
    ("E", "AndroidRuntime", "Process: io.loglens.sample, PID: %d" % PID),
    ("E", "AndroidRuntime", "java.lang.IllegalStateException: session already closed"),
    ("E", "AndroidRuntime", "\tat io.loglens.sample.ChatRepo.send(ChatRepo.kt:88)"),
    ("E", "AndroidRuntime", "\tat io.loglens.sample.ChatVm$send$1.invokeSuspend(ChatVm.kt:31)"),
]

LEGACY_NOISE = [
    ("D", "MainActivity", "@@@@@ onResume called"),
    ("D", "ChatFrag", "======= list size = 12"),
    ("V", "Utils", "test test 1234"),
]


class SyntheticSource(LogSource):
    name = "synth"

    def __init__(self, prefix: str = "APP", rate: float = 12.0, seed: int = 7,
                 burst: int = 0):
        super().__init__()
        self.prefix = prefix
        self.interval = 1.0 / rate if rate > 0 else 0.0
        self.rnd = random.Random(seed)
        self.burst = burst       # >0 이면 이만큼 즉시 뿜고 실시간 모드로 전환
        self._flow = itertools.count(1000)

    # -- 한 줄 조립 -----------------------------------------------------------
    def _line(self, level: str, tag: str, body: str, tid: int = PID) -> str:
        ts = datetime.now().strftime("%m-%d %H:%M:%S.") + f"{datetime.now().microsecond // 1000:03d}"
        return f"{ts} {PID:5d} {tid:5d} {level} {tag}: {body}"

    def _evt(self, level: str, domain: str, event: str, fields: str = "", msg: str = "") -> str:
        body = f"evt={event}"
        if fields:
            body += " " + fields
        if msg:
            body += " | " + msg
        return self._line(level, f"{self.prefix}_{domain}", body)

    # -- 시나리오 -------------------------------------------------------------
    def _login_flow(self) -> List[str]:
        fid = f"f{next(self._flow)}"
        uid = self.rnd.randint(100, 999)
        # 어디까지 진행되는지 — 뒤로 갈수록 이탈이 줄어드는 현실적인 퍼널
        depth = self.rnd.choices([1, 2, 3, 4, 5], weights=[4, 6, 8, 10, 62])[0]
        out = []
        for step in LOGIN_FUNNEL[:depth]:
            out.append(self._evt("I", "AUTH", step, f"flowId={fid} uid={uid}"))
        if depth < len(LOGIN_FUNNEL):
            reason = self.rnd.choice(["WRONG_PW", "NETWORK", "LOCKED", "EXPIRED"])
            out.append(self._evt("W", "AUTH", "LOGIN_FAIL",
                                 f"flowId={fid} uid={uid} reason={reason}",
                                 "로그인 실패"))
        return out

    def _chat(self) -> List[str]:
        if self.rnd.random() < 0.15:
            return [self._evt("E", "CHAT", "SEND_FAIL",
                              f"room={self.rnd.randint(1, 9)} err=SocketClosed",
                              "전송 실패, 재시도 예약")]
        return [self._evt("I", "CHAT", "MSG_SEND_OK",
                          f"room={self.rnd.randint(1, 9)} len={self.rnd.randint(1, 200)}")]

    def _net(self) -> List[str]:
        if self.rnd.random() < 0.2:
            return [self._evt("E", "NET", "REQUEST_FAIL",
                              f"host=api.example.test code={self.rnd.choice([500, 502, 408])} "
                              f"err=ConnectException:timeout")]
        return [self._evt("D", "NET", "REQUEST_OK",
                          f"host=api.example.test code=200 ms={self.rnd.randint(20, 900)}")]

    def _file(self) -> List[str]:
        ok = self.rnd.random() > 0.1
        fields = [f"size={self.rnd.randint(1024, 9_000_000)}",
                  f"name={self.rnd.choice(['a.png', 'report.pdf', '보고서.hwp'])}"]
        if not ok:
            fields.append("reason=QUOTA_EXCEEDED")
        return [self._evt("I" if ok else "E", "FILE_XFER",
                          "UPLOAD_DONE" if ok else "UPLOAD_FAIL",
                          " ".join(fields))]

    def _masked(self) -> List[str]:
        # emitter 마스킹이 걸린 모습 — 값은 항상 공백 없는 토큰이어야 한다
        return [self._evt("W", "AUTH", "TOKEN_REFRESH",
                          f"uid={self.rnd.randint(100, 999)} token=*** authType=oauth2",
                          "authType 은 마스킹되지 않는다 (정확 키 매칭)")]

    def _org(self) -> List[str]:
        """계층 화면을 한 단계 펼친 것처럼 찍는다.

        실제 앱과 똑같이 **펼친 노드만** 남는다. 그래서 뷰어는 언제나 부분 트리를 본다.
        """
        parent = self.rnd.choice([k for k in ORG_TREE if k is not None])
        kids = ORG_TREE[parent]
        node, title = self.rnd.choice(kids)
        sub = len(ORG_TREE.get(node, []))
        return [self._evt(
            "D", "ORG", "NODE_FETCH_OK",
            f"node={node} parent={parent} title={title} "
            f"children={sub} items={self.rnd.randint(0, 9)}",
            f"계층 호출: {title} 하위 {sub}개",
        )]

    def _org_root(self) -> List[str]:
        node, title = ORG_TREE[None][0]
        return [self._evt("D", "ORG", "NODE_FETCH_OK",
                          f"node={node} parent=- title={title} "
                          f"children={len(ORG_TREE.get(node, []))} items=0",
                          f"계층 호출: {title}")]

    def _legacy(self) -> List[str]:
        lv, tag, body = self.rnd.choice(LEGACY_NOISE)
        return [self._line(lv, tag, body)]

    def _crash(self) -> List[str]:
        return [self._line(lv, tag, body) for lv, tag, body in CRASH_STACK]

    def _anr(self) -> List[str]:
        return [self._line("E", "ActivityManager",
                           "ANR in io.loglens.sample (io.loglens.sample/.MainActivity)")]

    def _next_batch(self) -> List[str]:
        roll = self.rnd.random()
        if roll < 0.22:
            return self._login_flow()
        if roll < 0.45:
            return self._chat()
        if roll < 0.66:
            return self._net()
        if roll < 0.76:
            return self._file()
        if roll < 0.80:
            return self._masked()
        if roll < 0.84:
            return self._org_root()
        if roll < 0.92:
            return self._org()
        if roll < 0.96:
            return self._legacy()
        if roll < 0.99:
            return self._anr()
        return self._crash()

    # -- 스트림 ---------------------------------------------------------------
    def lines(self) -> Iterator[str]:
        yield marker("합성 로그 생성기 — 기기 불필요 (데모 모드)")
        emitted = 0
        while not self.stopped:
            for ln in self._next_batch():
                if self.stopped:
                    return
                yield ln
                emitted += 1
            if self.burst and emitted < self.burst:
                continue                       # 초기 버스트는 지연 없이
            if self.interval and self._stop.wait(self.interval):
                return

    def describe(self) -> dict:
        return {"kind": self.name, "prefix": self.prefix,
                "rate": round(1 / self.interval, 1) if self.interval else "max"}
