"""뷰어 설정 — 도메인 탭 / 이슈 규칙 / 프리픽스를 코드 밖으로 뺀다.

기획서 §6 "모듈화 — config 외부화". 탭과 이슈 규칙이 코드에 박혀 있으면
프로젝트마다 뷰어를 포크해야 한다. 여기서 전부 config.json 으로 뺀다.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .parser import Record

# 규칙이 검사할 수 있는 레코드 속성 화이트리스트.
_MATCHABLE = ("kind", "level", "tag", "domain", "event", "msg", "raw")


def _compile(pattern: str) -> re.Pattern:
    return re.compile(pattern)


@dataclass
class Tab:
    """도메인 탭. 원클릭 필터."""
    id: str
    label: str
    domains: List[str] = field(default_factory=list)
    # 점진 도입용: 아직 이관 안 된 레거시 태그도 같은 탭에 끌어온다 (기획서 §6).
    legacy_tag_pattern: Optional[str] = None
    _legacy_re: Optional[re.Pattern] = None

    def __post_init__(self):
        if self.legacy_tag_pattern:
            self._legacy_re = _compile(self.legacy_tag_pattern)

    def matches(self, rec: Record) -> bool:
        if rec.domain and rec.domain in self.domains:
            return True
        if self._legacy_re and rec.tag and self._legacy_re.search(rec.tag):
            return True
        return False

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "domains": self.domains,
                "legacyTagPattern": self.legacy_tag_pattern}


@dataclass
class IssueRule:
    """이슈 트레이 규칙: 무엇을 이슈로 볼지 + 어떻게 묶을지.

    when   : {속성: 정규식} — 전부 만족해야 매치 (AND)
    group  : 그룹 키 만드는 법
             {"regex": "..."} → raw 에서 첫 캡처그룹
             {"template": "{domain}/{event}"} → 속성 치환
    """
    id: str
    label: str
    severity: str = "error"
    when: Dict[str, str] = field(default_factory=dict)
    group: Dict[str, str] = field(default_factory=dict)
    _when: Dict[str, re.Pattern] = field(default_factory=dict, repr=False)
    _group_re: Optional[re.Pattern] = field(default=None, repr=False)

    def __post_init__(self):
        for k, v in self.when.items():
            if k not in _MATCHABLE:
                raise ValueError(
                    f"issue rule '{self.id}': 검사 불가 속성 '{k}'. "
                    f"허용: {', '.join(_MATCHABLE)}"
                )
            self._when[k] = _compile(v)
        if "regex" in self.group:
            self._group_re = _compile(self.group["regex"])

    def matches(self, rec: Record) -> bool:
        if not self._when:
            return False
        for attr, pat in self._when.items():
            val = getattr(rec, attr, None)
            if val is None or not pat.search(str(val)):
                return False
        return True

    def key(self, rec: Record) -> str:
        if self._group_re:
            m = self._group_re.search(rec.raw)
            if m:
                return m.group(1) if m.groups() else m.group(0)
            return self.group.get("fallback", self.label)
        tpl = self.group.get("template")
        if tpl:
            vals = {a: (getattr(rec, a, None) or "?") for a in _MATCHABLE}
            vals.update({f"f_{k}": v for k, v in rec.fields.items()})
            try:
                return tpl.format(**vals)
            except KeyError:
                return self.label
        return self.label

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "severity": self.severity}


@dataclass
class Funnel:
    """세션 퍼널: 순서가 있는 이벤트 목록. 단계별 이탈률을 본다."""
    id: str
    label: str
    domain: str
    steps: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label,
                "domain": self.domain, "steps": self.steps}


@dataclass
class Outcome:
    """이벤트 이름 접미사로 성공/실패를 판정한다 (기획서 §9-4 이름 거버넌스의 보상)."""
    success: List[str] = field(default_factory=lambda: ["_OK", "_SUCCESS", "_DONE"])
    failure: List[str] = field(default_factory=lambda: ["_FAIL", "_ERROR", "_TIMEOUT", "_DENIED"])
    # 실패 사유를 어느 필드에서 읽을지 (우선순위 순)
    reason_fields: List[str] = field(default_factory=lambda: ["reason", "err", "code"])

    def classify(self, event: Optional[str]) -> Optional[str]:
        if not event:
            return None
        for s in self.success:
            if event.endswith(s):
                return "success"
        for f in self.failure:
            if event.endswith(f):
                return "failure"
        return None


@dataclass
class Config:
    prefix: str = "APP"
    package: Optional[str] = None
    buffer_size: int = 20000
    tabs: List[Tab] = field(default_factory=list)
    issue_rules: List[IssueRule] = field(default_factory=list)
    funnels: List[Funnel] = field(default_factory=list)
    outcome: Outcome = field(default_factory=Outcome)

    @staticmethod
    def load(path: Optional[str]) -> "Config":
        if not path:
            return Config.default()
        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        return Config.from_dict(raw)

    @staticmethod
    def from_dict(d: dict) -> "Config":
        return Config(
            prefix=d.get("prefix", "APP"),
            package=d.get("package"),
            buffer_size=int(d.get("bufferSize", 20000)),
            tabs=[Tab(id=t["id"], label=t.get("label", t["id"]),
                      domains=t.get("domains", []),
                      legacy_tag_pattern=t.get("legacyTagPattern"))
                  for t in d.get("tabs", [])],
            issue_rules=[IssueRule(id=r["id"], label=r.get("label", r["id"]),
                                   severity=r.get("severity", "error"),
                                   when=r.get("when", {}), group=r.get("group", {}))
                         for r in d.get("issueRules", [])],
            funnels=[Funnel(id=f["id"], label=f.get("label", f["id"]),
                            domain=f.get("domain", ""), steps=f.get("steps", []))
                     for f in d.get("funnels", [])],
            outcome=Outcome(**{
                "success": d.get("outcome", {}).get("success", Outcome().success),
                "failure": d.get("outcome", {}).get("failure", Outcome().failure),
                "reason_fields": d.get("outcome", {}).get("reasonFields", Outcome().reason_fields),
            }),
        )

    @staticmethod
    def default() -> "Config":
        """config 없이도 돌아간다. 크래시/ANR 규칙은 어느 안드로이드 앱에서나 유효하다."""
        return Config.from_dict({
            "prefix": "APP",
            "issueRules": _DEFAULT_ISSUE_RULES,
        })

    def to_dict(self) -> dict:
        return {
            "prefix": self.prefix,
            "package": self.package,
            "tabs": [t.to_dict() for t in self.tabs],
            "issueRules": [r.to_dict() for r in self.issue_rules],
            "funnels": [f.to_dict() for f in self.funnels],
        }


_DEFAULT_ISSUE_RULES = [
    {
        "id": "crash",
        "label": "크래시",
        "severity": "fatal",
        # 예외 '클래스명'이 있는 줄만 잡는다. "FATAL EXCEPTION: main" 이나 `at ...`
        # 스택 프레임까지 잡으면 크래시 하나가 이슈 여러 개로 쪼개진다.
        "when": {"tag": "^AndroidRuntime$", "raw": r"[\w.$]+(?:Exception|Error)\b"},
        "group": {"regex": r"([\w.$]+(?:Exception|Error))\b", "fallback": "UnknownCrash"},
    },
    {
        "id": "anr",
        "label": "ANR",
        "severity": "fatal",
        "when": {"raw": r"\bANR in\b"},
        "group": {"regex": r"ANR in ([^\s(]+)", "fallback": "ANR"},
    },
    {
        "id": "native",
        "label": "네이티브 크래시",
        "severity": "fatal",
        "when": {"tag": "^(DEBUG|libc)$", "raw": r"signal \d+|Fatal signal"},
        "group": {"regex": r"(signal \d+[^,]*)", "fallback": "native"},
    },
    {
        "id": "structured_error",
        "label": "구조화 에러",
        "severity": "error",
        "when": {"kind": "^structured$", "level": "^E$"},
        "group": {"template": "{domain}/{event}"},
    },
]
