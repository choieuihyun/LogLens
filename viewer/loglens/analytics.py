"""집계 — 이슈 트레이 + 분석 대시보드.

기획서 §6: "구조화 로그라서 가능한, 범용 도구가 원리상 못 하는 것."
범용 logcat 뷰어는 문자열밖에 못 보므로 group-by 를 할 수 없다.
우리는 (domain, event, fields) 튜플을 갖고 있으니 그냥 집계하면 된다.
"""

from __future__ import annotations

from collections import Counter, OrderedDict
from typing import Dict, List, Optional

from .config import Config
from .parser import Record, STRUCTURED


class IssueTray:
    """이슈를 규칙별·그룹키별로 묶고 센다."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        # (rule_id, key) -> {count, first, last, sample}
        self._groups: "OrderedDict[tuple, dict]" = OrderedDict()

    def observe(self, rec: Record) -> Optional[dict]:
        for rule in self.cfg.issue_rules:
            if not rule.matches(rec):
                continue
            key = (rule.id, rule.key(rec))
            g = self._groups.get(key)
            if g is None:
                g = {
                    "ruleId": rule.id,
                    "ruleLabel": rule.label,
                    "severity": rule.severity,
                    "key": key[1],
                    "count": 0,
                    "firstTs": rec.ts,
                    "lastTs": rec.ts,
                    "sample": rec.raw,
                }
                self._groups[key] = g
            g["count"] += 1
            g["lastTs"] = rec.ts
            return g
        return None

    def snapshot(self) -> List[dict]:
        order = {"fatal": 0, "error": 1, "warn": 2, "info": 3}
        return sorted(
            self._groups.values(),
            key=lambda g: (order.get(g["severity"], 9), -g["count"]),
        )

    def clear(self):
        self._groups.clear()


def aggregate(records: List[Record], cfg: Config) -> dict:
    """대시보드용 집계. 버퍼 전체를 훑는다 (수만 건 수준이면 충분히 빠르다)."""
    levels = Counter()
    domains = Counter()
    events = Counter()
    # domain -> {success, failure}
    outcomes: Dict[str, Counter] = {}
    # domain -> reason -> count
    reasons: Dict[str, Counter] = {}
    structured = 0

    for r in records:
        levels[r.level] += 1
        if r.kind != STRUCTURED:
            continue
        structured += 1
        domains[r.domain] += 1
        events[f"{r.domain}/{r.event}"] += 1

        verdict = cfg.outcome.classify(r.event)
        if verdict:
            outcomes.setdefault(r.domain, Counter())[verdict] += 1
            if verdict == "failure":
                reason = _reason_of(r, cfg)
                reasons.setdefault(r.domain, Counter())[reason] += 1

    return {
        "total": len(records),
        "structured": structured,
        "structuredRatio": round(structured / len(records), 4) if records else 0.0,
        "levels": dict(levels),
        "domains": domains.most_common(),
        "topEvents": events.most_common(15),
        "successRates": [
            {
                "domain": d,
                "success": c.get("success", 0),
                "failure": c.get("failure", 0),
                "rate": round(c.get("success", 0) / (c.get("success", 0) + c.get("failure", 0)), 4)
                if (c.get("success", 0) + c.get("failure", 0)) else None,
            }
            for d, c in sorted(outcomes.items())
        ],
        "failureReasons": [
            {"domain": d, "reasons": c.most_common(8)} for d, c in sorted(reasons.items())
        ],
        "funnels": [_funnel(records, f) for f in cfg.funnels],
    }


def _reason_of(rec: Record, cfg: Config) -> str:
    for key in cfg.outcome.reason_fields:
        if key in rec.fields:
            return rec.fields[key]
    return "(사유 필드 없음)"


def _funnel(records: List[Record], f) -> dict:
    """단계별 이탈. 각 단계 이벤트가 몇 번 찍혔는지 세고, 직전 단계 대비 통과율을 낸다.

    한계: flowId 없이는 '같은 세션의 같은 흐름'을 이을 수 없다 (기획서 §9-5).
    flowId 필드가 있으면 그걸로 세션을 구분하고, 없으면 단순 카운트로 근사한다.
    """
    by_step = Counter()
    flows: Dict[str, set] = {}
    for r in records:
        if r.kind != STRUCTURED or r.domain != f.domain or r.event not in f.steps:
            continue
        by_step[r.event] += 1
        fid = r.fields.get("flowId")
        if fid:
            flows.setdefault(fid, set()).add(r.event)

    if flows:
        counts = [sum(1 for s in flows.values() if step in s) for step in f.steps]
        mode = "flowId"
    else:
        counts = [by_step.get(step, 0) for step in f.steps]
        mode = "count"

    steps = []
    for i, step in enumerate(f.steps):
        prev = counts[i - 1] if i else None
        steps.append({
            "event": step,
            "count": counts[i],
            "dropoff": round(1 - counts[i] / prev, 4) if prev else None,
        })
    return {"id": f.id, "label": f.label, "domain": f.domain,
            "mode": mode, "steps": steps}


# ── 계층 재구성 ──────────────────────────────────────────────────────────────

def build_tree(records: List[Record], cfg_tree) -> dict:
    """평평한 로그에서 계층을 되살린다.

    조직도처럼 "누르면 그 아래를 불러오는" 화면은 펼친 만큼만 로그가 남는다.
    그래서 뷰어가 보는 것은 **언제나 부분 트리**다. 세 가지를 견뎌야 한다.

    1. **부모를 못 본 노드** — 사용자가 중간부터 펼쳤을 때. 버리지 않고 별도 뿌리로 올린다.
    2. **같은 노드가 여러 번** — 접었다 펴면 또 찍힌다. 마지막 것으로 갱신하고 횟수를 센다.
    3. **순환 참조** — 서버 데이터가 서로를 가리키면 깊이 계산이 멈추지 않는다. 상한을 둔다.
    """
    nodes: Dict[str, dict] = {}
    order: List[str] = []

    for r in records:
        if not cfg_tree.matches(r):
            continue
        nid = r.fields.get(cfg_tree.node)
        if not nid:
            continue
        # 최상위 노드는 식별자가 비어 있을 수 있다("-"). 버리면 "자식이 몇 개여야 하는지"
        # 같은 정보가 통째로 날아간다. 예약 id 를 주고 살린다.
        if nid == "-":
            nid = ROOT_ID
        pid = r.fields.get(cfg_tree.parent)
        if pid == "-" or pid == nid:
            pid = None

        n = nodes.get(nid)
        if n is None:
            n = {
                "id": nid,
                "parent": pid,
                "name": r.fields.get(cfg_tree.name) if cfg_tree.name else None,
                "metrics": {},
                "hits": 0,
                "lastTs": None,
                "expected": None,     # 앱이 알려준 자식 수
                "loggedDepth": None,  # 앱이 적어 준 깊이 (검증용)
                "children": [],
            }
            nodes[nid] = n
            order.append(nid)
        # 접었다 펴면 또 찍힌다. 마지막 값으로 갱신하되 횟수는 누적한다.
        n["hits"] += 1
        n["lastTs"] = r.ts
        if pid:
            n["parent"] = pid
        if cfg_tree.name and r.fields.get(cfg_tree.name):
            n["name"] = r.fields[cfg_tree.name]
        for m in cfg_tree.metrics:
            if m in r.fields:
                n["metrics"][m] = r.fields[m]
        if cfg_tree.depth_field and cfg_tree.depth_field in r.fields:
            try:
                n["loggedDepth"] = int(r.fields[cfg_tree.depth_field])
            except ValueError:
                pass
        if cfg_tree.child_count and cfg_tree.child_count in r.fields:
            try:
                n["expected"] = int(r.fields[cfg_tree.child_count])
            except ValueError:
                pass

    # 부모-자식 잇기. 부모를 못 본 노드는 뿌리로 올린다.
    roots: List[dict] = []
    orphans = 0
    for nid in order:
        n = nodes[nid]
        p = nodes.get(n["parent"]) if n["parent"] else None
        if p is not None and p is not n:
            p["children"].append(n)
        else:
            if n["parent"]:
                n["orphan"] = True      # 부모 이름은 아는데 그 줄을 못 봄
                orphans += 1
            roots.append(n)

    # 최상위 노드를 봤다면, 부모 없는 나머지는 전부 그 아래로 모은다.
    # `parent=-` 는 "부모 없음"이 아니라 "최상위의 자식"이라는 뜻이기 때문이다.
    root_node = nodes.get(ROOT_ID)
    if root_node is not None and len(roots) > 1:
        adopted = [n for n in roots if n is not root_node and not n.get("orphan")]
        root_node["children"] = adopted + root_node["children"]
        roots = [root_node] + [n for n in roots if n is not root_node and n.get("orphan")]

    _assign_depth(roots)

    # depth 는 parent 와 중복 정보다. 트리는 parent 로만 세우고, depth 는 **검증**에 쓴다.
    # 어긋나면 parent 필드가 잘못 들어오고 있다는 신호다 (실제로 한 번 겪었다).
    depth_mismatch = 0
    if cfg_tree.depth_field:
        for n in nodes.values():
            if n.get("loggedDepth") is not None and n["loggedDepth"] != n.get("depth"):
                n["depthMismatch"] = True
                depth_mismatch += 1

    # 앱이 "자식 N개" 라고 했는데 그중 몇 개만 봤는지. 어디를 더 펼쳐야 하는지 알려준다.
    for n in nodes.values():
        n["missing"] = (max(0, n["expected"] - len(n["children"]))
                        if n["expected"] is not None else None)
    return {
        "id": cfg_tree.id,
        "label": cfg_tree.label,
        "roots": roots,
        "nodeCount": len(nodes),
        "rootCount": len(roots),
        "orphanCount": orphans,
        "maxDepth": max((_max_depth(r) for r in roots), default=0),
        "missingTotal": sum(n["missing"] or 0 for n in nodes.values()),
        "depthMismatch": depth_mismatch,
    }


ROOT_ID = "(root)"      # 식별자가 비어 있는 최상위 노드에 주는 예약 id
_DEPTH_MAX = 64     # 서버 데이터가 서로를 가리켜도 멈추게 한다


def _assign_depth(roots: List[dict]) -> None:
    stack = [(r, 0) for r in reversed(roots)]
    seen = set()
    while stack:
        n, d = stack.pop()
        if id(n) in seen or d > _DEPTH_MAX:
            n["children"] = []          # 순환이면 잘라낸다
            continue
        seen.add(id(n))
        n["depth"] = d
        for c in reversed(n["children"]):
            stack.append((c, d + 1))


def _max_depth(n: dict) -> int:
    if not n["children"]:
        return n.get("depth", 0)
    return max(_max_depth(c) for c in n["children"])
