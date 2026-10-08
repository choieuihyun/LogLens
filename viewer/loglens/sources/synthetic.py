"""합성 소스 — 기기 없이 뷰어 전체를 돌리는 데모 생성기.

기기/adb 없이도 `loglens --source synth` 하나로 탭·이슈트레이·대시보드가
전부 살아 있는 화면을 보여준다. README 의 GIF 를 이걸로 찍는다.

의도적으로 섞어 넣는 것들:
  - 성공/실패가 섞인 도메인 트래픽 (성공률 차트가 의미를 갖도록)
  - flowId 로 이어지는 로그인 퍼널 (중간 이탈 포함)
  - 레거시 자유형식 로그 (점진 도입 시나리오)
  - 크래시 스택 / ANR (이슈 트레이)
  - 응답 본문을 통째로 실은 원문 (짧은 JSON, 여러 줄로 나뉜 긴 JSON, XML, 조각이 빠진 경우)
"""

from __future__ import annotations

import itertools
import random
import time
from datetime import datetime
from typing import Iterator, List

from .. import payloads
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

# 로그인 직후 서버가 내려주는 설정 목록. 항목 하나당 한 줄로 찍힌다 (한 줄에 다 넣으면 4KB 에 잘린다).
# 같은 코드가 여러 번 나오고(FEAT_OPT), 값 안에 구조가 들어 있는(K=V 목록, JSON) 실제 모양을 흉내낸다.
# 표 화면과 묶음 비교를 데모하려는 것이라 로그인마다 조금씩 달라진다.
RULE_ITEMS = [
    ("FEAT_CHAT_1", "MAX=200", "-"),
    ("FEAT_CHAT_2", "INVITE=TRUE,JOIN=TRUE,LEAVE=TRUE", "-"),
    ("FEAT_FILE_1", "100", "-"),
    ("FEAT_FILE_2", "doc,pdf,png,jpg,zip", "-"),
    ("FEAT_ORG_1", "demo", "조직도"),
    ("FEAT_URL_1", "https://app.example.test/notice", "UM=GET,WD=350,HG=620"),
    ("FEAT_UI_1", '{"view":{"compact":true,"avatar":false},"tabs":["chat","org"]}', "-"),
    ("FEAT_OPT", "TYPE=INTEGER,SECTION=chat,IDENT=new_line,VALUE=1", "-"),
    ("FEAT_OPT", "TYPE=INTEGER,SECTION=option,IDENT=search_recv,VALUE=1", "-"),
    ("FEAT_OPT", "TYPE=STRING,SECTION=remote,IDENT=host,VALUE=relay.example.test", "-"),
    ("FEAT_STATE_1", "자리_비움", "VISIBLE=TRUE"),
    ("FEAT_EMPTY_1", "-", "-"),
    ("FEAT_EMPTY_2", "-", "-"),
]

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
        self._pl = itertools.count(1)
        # 실행마다 다른 접두어. 스냅샷을 켜 두면 재시작 후 같은 flowId 가 옛 묶음을 덮어쓴다.
        self._run = format(int(time.time()) % 4096, "03x")

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

    def _payload(self, domain: str, event: str, text: str, fields: str = "",
                 chunk_bytes: int = 3400, lose: bool = False) -> List[str]:
        """원문을 라이브러리와 같은 모양으로 찍는다 (docs/RECORD_FORMAT.md 8절).

        이 생성기는 계약을 흉내내는 쪽이라 어긋나기 쉽다. tests/test_payloads.py 가 여기서 나온 줄을
        뷰어의 조립 경로에 넣어 글자 그대로 돌아오는지 본다.
        lose 면 가운데 조각 하나를 빼서 logcat 이 줄을 잃은 상황을 만든다.
        """
        parts, cur, size = [], [], 0
        budget = chunk_bytes - 16                                 # 가장자리 보정 여유
        for ch in text:
            # 글자 하나만 넘기면 가장자리로 보고 공백을 바꿔 버린다. 안쪽 글자의 폭을 잰다.
            w = len(payloads.escape(f"x{ch}x").encode("utf-8")) - 2
            if size + w > budget and cur:
                parts.append("".join(cur))
                cur, size = [], 0
            cur.append(ch)
            size += w
        parts.append("".join(cur))
        pl_id = f"{self._run}{next(self._pl):x}"
        head = f"evt={event}{' ' + fields if fields else ''} plId={pl_id}"
        tail = f"plParts={len(parts)} plBytes={len(text.encode('utf-8'))}"
        out = []
        for i, p in enumerate(parts, 1):
            if lose and len(parts) > 2 and i == 2:
                continue
            body = f"{head} plPart={i} {tail}" + (f" | {payloads.escape(p)}" if p else "")
            out.append(self._line("D", f"{self.prefix}_{domain}", body))
        return out

    def _address_book(self, n: int) -> str:
        rows = ",".join(f'{{"uid":{100 + i},"name":"사용자 {i + 1}","dept":"개발 {1 + i % 4}팀",'
                        f'"mobile":"***","memo":"첫 줄\\n둘째 줄"}}' for i in range(n))
        return f'{{"result":"ok","count":{n},"list":[{rows}]}}'

    # -- 시나리오 -------------------------------------------------------------
    def _login_flow(self) -> list:
        """로그인 한 번. 단계 사이에 실제 같은 간격을 둔다 (흐름 타임라인이 의미를 갖도록).

        반환 목록의 항목은 두 종류다: 초(float) = 그만큼 쉰다, 함수 = 부르는 시점의 시각으로 한 줄.
        줄을 미리 만들어 두면 시각이 전부 같아져 단계 간격이 0ms 로 찍힌다.
        """
        fid = f"f{self._run}{next(self._flow)}"
        uid = self.rnd.randint(100, 999)
        # 어디까지 진행되는지 — 뒤로 갈수록 이탈이 줄어드는 현실적인 퍼널
        depth = self.rnd.choices([1, 2, 3, 4, 5], weights=[4, 6, 8, 10, 62])[0]
        # 단계마다 평소 간격(ms). 가끔 한 단계가 크게 느려진다 (기준선 비교 데모용)
        gap = {"CREDENTIAL_CHECK": (30, 80), "TOKEN_ISSUE": (90, 220),
               "PROFILE_FETCH": (120, 280), "LOGIN_OK": (40, 110)}
        slow = self.rnd.choice(list(gap)) if self.rnd.random() < 0.15 else None
        out: list = []
        for i, step in enumerate(LOGIN_FUNNEL[:depth]):
            if step in gap:
                lo, hi = gap[step]
                ms = self.rnd.randint(lo, hi) * (self.rnd.randint(5, 9) if step == slow else 1)
                out.append(ms / 1000.0)
            out.append(lambda step=step: self._evt("I", "AUTH", step, f"flowId={fid} uid={uid}"))
            if i == 0 and depth > 1:
                out.append(0.05)
                out += self._rules(fid)
        if depth < len(LOGIN_FUNNEL):
            reason = self.rnd.choice(["WRONG_PW", "NETWORK", "LOCKED", "EXPIRED"])
            out.append(self.rnd.randint(200, 600) / 1000.0)
            if reason == "NETWORK":
                # 실패 직전 시스템 쪽 에러 — 타임라인이 "그 시간대에 끼어 있던 로그" 로 보여준다
                out.append(lambda: self._line("E", "OkHttp",
                                              "java.net.SocketTimeoutException: timeout"))
            out.append(lambda: self._evt("W", "AUTH", "LOGIN_FAIL",
                                         f"flowId={fid} uid={uid} reason={reason}",
                                         "로그인 실패"))
        return out

    def _rules(self, fid: str) -> List[str]:
        """서버 설정 목록. 순서는 매번 섞이고, 가끔 값 하나가 바뀌거나 항목 하나가 빠진다."""
        items = list(RULE_ITEMS)
        self.rnd.shuffle(items)
        if self.rnd.random() < 0.5:
            items.pop(self.rnd.randrange(len(items)))
        if self.rnd.random() < 0.5:
            items.append(("FEAT_NEW_1", "ON", "-"))
        items = [(c, "MAX=500" if c == "FEAT_CHAT_1" and self.rnd.random() < 0.5 else v1, v2)
                 for c, v1, v2 in items]
        # 가끔 서버가 형식이 틀린 값을 내려준다 (숫자 자리에 단위가 붙음) — 형식 검사 데모용
        items = [(c, "100MB" if c == "FEAT_FILE_1" and self.rnd.random() < 0.3 else v1, v2)
                 for c, v1, v2 in items]
        # 줄은 쓰는 순간 만든다. 미리 만들면 시각이 앞 단계보다 이르게 찍힌다.
        out = [(lambda c=c, v1=v1, v2=v2: self._evt(
                    "D", "AUTH", "RULE_ITEM", f"flowId={fid} code={c} value1={v1} value2={v2}"))
               for c, v1, v2 in items]
        out.append(lambda: self._evt("I", "AUTH", "RULE_SUMMARY", f"flowId={fid} count={len(items)}",
                                     "서버 설정 수신 완료"))
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
        # 응답 본문을 통째로 남기는 요청만 flowId 를 단다 (요약 로그와 원문을 잇는 용도).
        # 전부 달면 한 줄짜리 흐름이 흐름 목록을 덮는다.
        roll = self.rnd.random()
        fid = f"n{self._run}{next(self._flow)}"
        flow = f"flowId={fid} " if roll < 0.40 else ""
        out = [self._evt("D", "NET", "REQUEST_OK",
                         f"{flow}host=api.example.test code=200 ms={self.rnd.randint(20, 900)}")]
        # 요약 로그와 이벤트 이름을 달리하고 같은 flowId 로 잇는다.
        if roll < 0.25:
            out += self._payload("NET", "RESPONSE_BODY", self._address_book(self.rnd.randint(2, 5)),
                                 f"flowId={fid}")
        elif roll < 0.33:
            # 한 줄 한도를 넘는 본문 — 여러 줄로 나뉜다. 가끔은 가운데 조각이 빠진다.
            out += self._payload("NET", "RESPONSE_BODY", self._address_book(self.rnd.randint(90, 160)),
                                 f"flowId={fid}", lose=self.rnd.random() < 0.3)
        elif roll < 0.40:
            xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<org id="N1" name="본사">\n'
                   + "".join(f'  <dept id="N1{i}" name="부서 {i}"><member uid="{100 + i}">사용자 {i}</member></dept>\n'
                             for i in range(1, self.rnd.randint(3, 7)))
                   + "</org>")
            out += self._payload("NET", "RESPONSE_BODY", xml, f"flowId={fid}")
        return out

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
            f"node={node} parent={parent} title={title} depth={len(node) - 1} "
            f"children={sub} items={self.rnd.randint(0, 9)}",
            f"계층 호출: {title} 하위 {sub}개",
        )]

    def _org_root(self) -> List[str]:
        node, title = ORG_TREE[None][0]
        return [self._evt("D", "ORG", "NODE_FETCH_OK",
                          f"node={node} parent=- title={title} depth=0 "
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
            for item in self._next_batch():
                if self.stopped:
                    return
                if isinstance(item, float):
                    # 초기 버스트 중에는 쉬지 않는다
                    if not (self.burst and emitted < self.burst) and self._stop.wait(item):
                        return
                    continue
                yield item() if callable(item) else item
                emitted += 1
            if self.burst and emitted < self.burst:
                continue                       # 초기 버스트는 지연 없이
            if self.interval and self._stop.wait(self.interval):
                return

    def describe(self) -> dict:
        return {"kind": self.name, "prefix": self.prefix,
                "rate": round(1 / self.interval, 1) if self.interval else "max"}
