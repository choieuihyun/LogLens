"""LogLens 레코드 파서.

계약은 docs/RECORD_FORMAT.md. 여기가 그 계약의 소비자 쪽 구현이다.

설계 원칙 2가지:

1. **접두사와 본문을 분리한다.** 접두사(타임스탬프/pid/레벨/태그)는 소스마다 다르다
   (logcat threadtime, logcat brief, 우리 파일 싱크). 본문(`evt=... k=v ... | msg`)만이
   진짜 계약이다. 그래서 얇은 접두사 파서 여러 개 + 공용 본문 파서 하나.

2. **절대 예외를 던지지 않는다.** 잘린 줄, 레거시 자유형식, 스택트레이스 조각이 다 들어온다.
   파싱 실패는 예외가 아니라 RAW 로의 강등이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as _dc_field
from typing import Dict, List, Optional

STRUCTURED = "structured"
UNSTRUCTURED = "unstructured"
RAW = "raw"

LEVELS = ("V", "D", "I", "W", "E")
_LEVEL_ALIAS = {"F": "E", "A": "E", "S": "V"}

# ── 접두사 파서들 ────────────────────────────────────────────────────────────
# 순서 중요: 더 구체적인(=타임스탬프 있는) 패턴이 먼저.
_PREFIX_PATTERNS: List[tuple] = [
    # 파일 싱크:  2026-08-12 11:23:45.678 I/APP_AUTH: body
    ("filesink", re.compile(
        r"^(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}) "
        r"(?P<level>[VDIWEFAS])/(?P<tag>[^:]+?)\s*: (?P<body>.*)$"
    )),
    # logcat -v threadtime:  08-12 11:23:45.678  4321  4390 E APP_NET: body
    ("threadtime", re.compile(
        r"^(?P<ts>\d\d-\d\d \d\d:\d\d:\d\d\.\d{3})\s+"
        r"(?P<pid>\d+)\s+(?P<tid>\d+)\s+"
        r"(?P<level>[VDIWEFAS])\s+(?P<tag>.*?)\s*: (?P<body>.*)$"
    )),
    # logcat -v time:  08-12 11:23:45.678 E/APP_NET( 4321): body
    ("time", re.compile(
        r"^(?P<ts>\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}) "
        r"(?P<level>[VDIWEFAS])/(?P<tag>[^(:]*?)\s*"
        r"(?:\(\s*(?P<pid>\d+)\))?\s*: (?P<body>.*)$"
    )),
    # logcat -v brief:  I/APP_AUTH( 4321): body   /  E/APP_NET:  body
    ("brief", re.compile(
        r"^(?P<level>[VDIWEFAS])/(?P<tag>[^(:]*?)\s*"
        r"(?:\(\s*(?P<pid>\d+)\))?\s*:\s+(?P<body>.*)$"
    )),
]

# ── 본문 파서 (진짜 계약) ────────────────────────────────────────────────────
_BODY = re.compile(
    r"^evt=(?P<event>[^\s|]+)"
    r"(?P<fields>(?:\s+[A-Za-z_][A-Za-z0-9_]*=[^\s|]+)*)"
    r"(?:\s+\|\s?(?P<msg>.*))?$"
)
_FIELD = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s|]+)")

TRUNCATION_MARK = "...[cut]"


@dataclass
class Record:
    raw: str
    kind: str = RAW
    ts: Optional[str] = None
    level: str = "I"
    tag: Optional[str] = None
    domain: Optional[str] = None
    event: Optional[str] = None
    fields: Dict[str, str] = _dc_field(default_factory=dict)
    msg: Optional[str] = None
    pid: Optional[int] = None
    tid: Optional[int] = None
    truncated: bool = False

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "ts": self.ts,
            "level": self.level,
            "tag": self.tag,
            "domain": self.domain,
            "event": self.event,
            "fields": self.fields,
            "msg": self.msg,
            "pid": self.pid,
            "tid": self.tid,
            "truncated": self.truncated,
            "raw": self.raw,
        }


class Parser:
    """prefix 를 알고 있는 파서. prefix 는 config 에서 오므로 반드시 이스케이프한다."""

    def __init__(self, prefix: str = "APP"):
        self.prefix = prefix
        # prefix 는 사용자 config 값 → 정규식 메타문자가 들어올 수 있다.
        self._tag_re = re.compile(
            r"^" + re.escape(prefix) + r"_(?P<domain>[A-Z0-9_]+)$"
        )

    # -- public ---------------------------------------------------------------
    def parse(self, line: str) -> Record:
        line = line.rstrip("\r\n")
        rec = Record(raw=line)
        if not line.strip():
            return rec

        pre = self._match_prefix(line)
        if pre is None:
            # logcat 구분선("--------- beginning of main") 같은 것도 여기로 온다.
            return rec

        rec.ts = pre.get("ts")
        rec.level = _LEVEL_ALIAS.get(pre["level"], pre["level"])
        rec.tag = pre["tag"]
        rec.pid = int(pre["pid"]) if pre.get("pid") else None
        rec.tid = int(pre["tid"]) if pre.get("tid") else None
        body = pre["body"]

        # 줄 끝 공백 하나로 레코드 전체가 강등되면 안 된다. emitter 가 안 만들어야 할
        # 것이지만, 파서는 관용적이어야 한다 (실제로 이 한 칸에 당해봤다).
        body = body.rstrip()

        m = self._tag_re.match(rec.tag or "")
        if m is None:
            # 우리 태그가 아니다 → 레거시/시스템 로그. 버리지 않고 그대로 보여준다.
            rec.kind = UNSTRUCTURED
            rec.msg = body
            return rec

        rec.domain = m.group("domain")
        b = _BODY.match(body)
        if b is None:
            # 우리 태그인데 본문이 규격 위반(잘렸거나, 아직 미이관 call site).
            rec.kind = UNSTRUCTURED
            rec.msg = body
            rec.truncated = body.endswith(TRUNCATION_MARK)
            return rec

        rec.kind = STRUCTURED
        rec.event = b.group("event")
        rec.fields = dict(_FIELD.findall(b.group("fields") or ""))
        rec.msg = b.group("msg")
        rec.truncated = line.endswith(TRUNCATION_MARK)
        return rec

    def parse_lines(self, lines) -> List[Record]:
        return [self.parse(ln) for ln in lines]

    # -- internal -------------------------------------------------------------
    @staticmethod
    def _match_prefix(line: str) -> Optional[dict]:
        for _name, pat in _PREFIX_PATTERNS:
            m = pat.match(line)
            if m:
                return m.groupdict()
        return None
