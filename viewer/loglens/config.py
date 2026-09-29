"""뷰어 설정 — 도메인 탭 / 이슈 규칙 / 프리픽스를 코드 밖으로 뺀다.

기획서 §6 "모듈화 — config 외부화". 탭과 이슈 규칙이 코드에 박혀 있으면
프로젝트마다 뷰어를 포크해야 한다. 여기서 전부 config.json 으로 뺀다.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .parser import Record, STRUCTURED

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
class Tree:
    """계층 로그를 트리로 다시 세우는 규칙.

    조직도나 주소록처럼 "누르면 그 아래를 불러오는" 화면은 로그가 평평하게 쌓입니다.
    각 줄에 자기 부모가 적혀 있으면 계층을 되살릴 수 있습니다.

    뷰어는 언제나 **부분 트리**만 봅니다. 사용자가 펼친 것만 로그가 찍히니까요.
    그래서 부모를 못 찾은 노드도 버리지 않고 별도 뿌리로 올립니다.
    """
    id: str
    label: str
    domain: str
    events: List[str] = field(default_factory=list)
    node: str = "id"            # 이 노드의 식별자가 든 필드
    parent: str = "parent"      # 부모 식별자가 든 필드
    name: Optional[str] = None  # 화면에 보여줄 이름 필드 (없으면 식별자만)
    metrics: List[str] = field(default_factory=list)  # 노드에 같이 표시할 숫자 필드
    # 자식이 몇 개 있어야 하는지 앱이 알려주는 필드 (예: subDept).
    # 실제로 본 자식 수와 비교해 "아직 안 펼친 게 몇 개" 인지 보여준다.
    child_count: Optional[str] = None
    # 앱이 적어 준 깊이 필드 (예: depth). 트리는 parent 로만 세우고, 이건 검증에만 쓴다.
    # 재구성한 깊이와 어긋나면 parent 가 잘못 들어오고 있다는 신호다.
    depth_field: Optional[str] = None
    # 최상위 컨테이너가 여럿일 때 서로 섞이지 않게 나누는 필드 (예: orgId).
    # 없으면 전부 한 묶음으로 본다.
    scope: Optional[str] = None
    # 말단에 붙는 다른 종류의 노드 (예: 부서 아래의 사람).
    # {"events": [...], "node": "uid", "parent": "dept", "name": "name",
    #  "truncatedEvent": "...", "truncatedCount": "skipped"}
    leaf: Dict[str, object] = field(default_factory=dict)

    def leaf_matches(self, rec: Record) -> bool:
        evs = self.leaf.get("events") or []
        return (bool(evs) and rec.kind == STRUCTURED
                and rec.domain == self.domain and rec.event in evs)

    def truncated_matches(self, rec: Record) -> bool:
        ev = self.leaf.get("truncatedEvent")
        return (bool(ev) and rec.kind == STRUCTURED
                and rec.domain == self.domain and rec.event == ev)

    def matches(self, rec: Record) -> bool:
        if rec.kind != STRUCTURED or rec.domain != self.domain:
            return False
        return not self.events or rec.event in self.events

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "domain": self.domain,
                "events": self.events, "node": self.node, "parent": self.parent,
                "name": self.name, "metrics": self.metrics,
                "childCount": self.child_count, "depthField": self.depth_field,
                "scope": self.scope, "leaf": self.leaf}


@dataclass
class Table:
    """목록처럼 쏟아지는 로그를 표로 묶는 규칙.

    서버 설정 목록처럼 한 번에 수십~수백 개가 오는 데이터는 앱이 항목 하나당 한 줄로 찍는다.
    한 줄에 통째로 찍으면 logcat 의 4KB 제한에 잘리기 때문이다. 전송은 그게 맞지만
    로그 목록에서 보면 흐름이 전부 묻힌다. 그래서 같은 묶음(groupBy)끼리 모아 표로 보여준다.

    key 는 행을 가르는 필드다. 한 묶음 안에서 같은 key 가 여러 번 나올 수 있고
    (같은 코드에 값이 여럿), 순서도 매번 다르다. 비교가 줄 단위가 아니라 key 단위인 이유다.
    """
    id: str
    label: str
    domain: str
    events: List[str] = field(default_factory=list)
    key: str = "code"
    # 한 묶음을 가르는 필드 (예: flowId). 없으면 전부 한 묶음이다.
    group_by: Optional[str] = None
    # 묶음이 다 왔는지 판단할 근거. 앱이 "몇 개 보냈다" 를 따로 찍어 주면 그 이벤트와 필드.
    # 링 버퍼가 오래된 묶음의 앞부분을 밀어냈을 때 비교가 가짜 "삭제" 를 내지 않게 한다.
    count_event: Optional[str] = None
    count_field: Optional[str] = None
    # 앱이 처리하도록 구현해 둔 key 목록. 들어왔는지만으로 동작하는 항목이 있어서
    # "값이 있나" 가 아니라 "들어왔나" 를 봐야 한다. 목록에 있는데 안 들어온 것을 꺼진 상태로 보여준다.
    # 항목은 "CODE" 문자열 또는 {"code": ..., "name": ..., "note": ..., 검사 키들}.
    # 검사 키: type(int|bool|url|json|kv) / pattern(정규식) / keys(kv 에 있어야 할 키) /
    #          field(검사할 필드, 기본 value1) / required(비어 있으면 문제로 본다)
    catalog: List[Dict[str, object]] = field(default_factory=list)
    # 구현 목록을 앱 소스에서 뽑는 규칙. 손으로 적은 catalog 는 그 위에 덮어쓴다 (이름·검사 키 보강용).
    # {"root": 소스 루트, "pattern": 캡처그룹 1이 key 인 정규식, "include": ["*.java", "*.kt"]}
    catalog_source: Dict[str, object] = field(default_factory=dict)
    # 묶음을 사람이 알아볼 이름으로 부른다. 같은 묶음 값을 가진 다른 이벤트에서 필드를 읽는다.
    # {"event": "LOGIN_START", "field": "uid"} — flowId 대신 계정으로 묶음을 고를 수 있다.
    label_from: Dict[str, str] = field(default_factory=dict)
    # catalog 의 where(파일:줄)를 여는 링크 틀. {abs} {path} {line} 을 채운다.
    # 예: "vscode://file{abs}:{line}" ({abs} 가 / 로 시작하므로 file 뒤에 / 를 붙이지 않는다)
    source_link: Optional[str] = None
    # catalog 의 where 를 뷰어 서버가 직접 여는 명령. 인자 목록이며 {abs} {path} {line} 을 채운다.
    # 브라우저 링크(sourceLink)로는 편집기를 못 고를 때 쓴다 (예: 같은 URL 스킴을 쓰는 IDE 가 여럿).
    # 예: ["/Applications/Android Studio.app/Contents/MacOS/studio", "--line", "{line}", "{abs}"]
    source_open: List[str] = field(default_factory=list)
    catalog_manual: List[Dict[str, object]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self.catalog_manual = normalize_catalog(self.catalog)
        self.catalog = [dict(c) for c in self.catalog_manual]

    def matches(self, rec: Record) -> bool:
        return (rec.kind == STRUCTURED and rec.domain == self.domain
                and rec.event in self.events)

    def count_matches(self, rec: Record) -> bool:
        return (bool(self.count_event) and rec.kind == STRUCTURED
                and rec.domain == self.domain and rec.event == self.count_event)

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "domain": self.domain,
                "events": self.events, "key": self.key, "groupBy": self.group_by,
                "countEvent": self.count_event, "countField": self.count_field,
                "catalog": self.catalog, "labelFrom": self.label_from or None,
                "sourceRoot": self.source_root(), "sourceLink": self.source_link,
                "sourceOpen": bool(self.source_open)}

    def source_root(self) -> Optional[str]:
        root = (self.catalog_source or {}).get("root")
        return os.path.abspath(os.path.expanduser(str(root))) if root else None


_CATALOG_KEYS = ("name", "note", "where", "type", "pattern", "keys", "field", "required")


def normalize_catalog(items) -> List[Dict[str, object]]:
    """catalog 항목을 한 모양으로. 모양이 틀린 항목은 버린다.

    설정 오타 하나로 뷰어가 안 뜨면 안 된다. 그래서 예외 대신 버린다.
    """
    norm = []
    for c in items or []:
        if isinstance(c, str):
            norm.append({"code": c, "name": None, "note": None})
        elif isinstance(c, dict) and c.get("code"):
            e = {"code": str(c["code"]), "name": c.get("name"), "note": c.get("note")}
            for k in _CATALOG_KEYS:
                if k in c and k not in e:
                    e[k] = c[k]
            norm.append(e)
    return norm


def merge_catalog(base: List[dict], over: List[dict]) -> List[dict]:
    """소스에서 뽑은 목록(base) 위에 손으로 적은 목록(over)을 덮는다. 값이 있는 키만 덮는다."""
    out = {c["code"]: dict(c) for c in base}
    for c in over:
        cur = out.setdefault(c["code"], {"code": c["code"], "name": None, "note": None})
        for k, v in c.items():
            if v is not None:
                cur[k] = v
    return list(out.values())


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
    # 표 묶음을 파일로 남길 곳. 비우면 남기지 않는다 (버퍼가 비워지면 사라진다).
    snapshot_dir: Optional[str] = None
    # 로그 한 줄 → 그 로그를 만든 코드 줄. {"root", "open": [명령 인자], "pattern"?, "include"?}
    # pattern 을 비우면 LogLens 호출(LogLens.i(도메인, "이벤트", ...))로 찾는다.
    event_source: Dict[str, object] = field(default_factory=dict)
    # 흐름을 잇는 필드와 이름으로 쓸 필드. 기본 {"field": "flowId", "labelField": "uid"}
    flow: Dict[str, str] = field(default_factory=dict)
    # 이름 검사에 쓸 동의어 묶음. 표기로는 못 잡는 것(uid / userId)만 적는다. 기본은 비어 있다.
    synonyms: List[List[str]] = field(default_factory=list)
    tabs: List[Tab] = field(default_factory=list)
    issue_rules: List[IssueRule] = field(default_factory=list)
    funnels: List[Funnel] = field(default_factory=list)
    trees: List[Tree] = field(default_factory=list)
    tables: List[Table] = field(default_factory=list)
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
            snapshot_dir=d.get("snapshotDir"),
            event_source=d.get("eventSource") or {},
            flow=d.get("flow") or {},
            synonyms=[list(map(str, g)) for g in ((d.get("naming") or {}).get("synonyms") or [])
                      if isinstance(g, list)],
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
            trees=[Tree(id=x["id"], label=x.get("label", x["id"]),
                        domain=x["domain"], events=x.get("events", []),
                        node=x.get("node", "id"), parent=x.get("parent", "parent"),
                        name=x.get("name"), metrics=x.get("metrics", []),
                        child_count=x.get("childCount"),
                        depth_field=x.get("depthField"),
                        scope=x.get("scope"), leaf=x.get("leaf", {}))
                   for x in d.get("trees", [])],
            tables=[Table(id=x["id"], label=x.get("label", x["id"]),
                          domain=x["domain"], events=x.get("events", []),
                          key=x.get("key", "code"), group_by=x.get("groupBy"),
                          count_event=x.get("countEvent"),
                          count_field=x.get("countField"),
                          catalog=x.get("catalog", []),
                          catalog_source=x.get("catalogSource") or {},
                          label_from=x.get("labelFrom") or {},
                          source_link=x.get("sourceLink"),
                          source_open=[str(a) for a in (x.get("sourceOpen") or [])])
                    for x in d.get("tables", [])],
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
            "snapshots": bool(self.snapshot_dir),
            "flow": {"field": (self.flow or {}).get("field") or "flowId",
                     "labelField": (self.flow or {}).get("labelField") or "uid"},
            # 명령·경로는 브라우저로 보내지 않는다. 쓸 수 있는지만 알린다.
            "eventSource": bool(self.event_source.get("root") and self.event_source.get("open")),
            "package": self.package,
            "tabs": [t.to_dict() for t in self.tabs],
            "issueRules": [r.to_dict() for r in self.issue_rules],
            "funnels": [f.to_dict() for f in self.funnels],
            "trees": [x.to_dict() for x in self.trees],
            "tables": [x.to_dict() for x in self.tables],
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
