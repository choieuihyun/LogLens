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

ROOT_ID = "(root)"      # 식별자가 비어 있는 최상위 노드에 주는 예약 id
_DEPTH_MAX = 64         # 서버 데이터가 서로를 가리켜도 멈추게 한다


def build_tree(records: List[Record], cfg_tree) -> dict:
    """평평한 로그에서 계층을 되살린다.

    조직도처럼 "누르면 그 아래를 불러오는" 화면은 펼친 만큼만 로그가 남는다.
    그래서 뷰어가 보는 것은 **언제나 부분 트리**다. 견뎌야 하는 것들:

    1. **부모를 못 본 노드** — 중간부터 펼쳤을 때. 버리지 않고 뿌리로 올린다.
    2. **같은 노드가 여러 번** — 접었다 펴면 또 찍힌다. 마지막 값으로 갱신하고 횟수를 센다.
    3. **순환 참조** — 깊이 상한을 둔다.
    4. **최상위 컨테이너가 여럿** — 식별자가 비어 있는 루트가 둘이면 한 노드로 합쳐져
       서로 다른 조직의 부서가 섞인다. `scope` 필드로 나눈다.
    5. **말단에 다른 종류의 노드** — 부서 아래의 사람 같은 것. 같은 사람이 여러 부서에
       나올 수 있으므로 **부모+식별자**를 키로 쓴다.
    """
    scope_f = cfg_tree.scope
    nodes: Dict[tuple, dict] = {}      # (scope, id) -> node
    order: List[tuple] = []
    truncated: Dict[tuple, int] = {}   # (scope, parent id) -> 로그에 안 남긴 수

    def scope_of(r: Record) -> str:
        return r.fields.get(scope_f, "") if scope_f else ""

    def touch(key, ident, parent, name, kind):
        n = nodes.get(key)
        if n is None:
            n = {"id": ident, "scope": key[0], "parent": parent, "name": name,
                 "kind": kind, "metrics": {}, "hits": 0, "lastTs": None,
                 "expected": None, "loggedDepth": None, "truncated": 0,
                 "children": []}
            nodes[key] = n
            order.append(key)
        n["hits"] += 1
        if parent:
            n["parent"] = parent
        if name:
            n["name"] = name
        return n

    for r in records:
        sc = scope_of(r)

        if cfg_tree.truncated_matches(r):
            pid = r.fields.get(cfg_tree.leaf.get("parent", "parent"))
            cnt = r.fields.get(cfg_tree.leaf.get("truncatedCount", "skipped"))
            try:
                truncated[(sc, pid)] = truncated.get((sc, pid), 0) + int(cnt)
            except (TypeError, ValueError):
                pass
            continue

        if cfg_tree.leaf_matches(r):
            leaf = cfg_tree.leaf
            ident = r.fields.get(leaf.get("node", "id"))
            pid = r.fields.get(leaf.get("parent", "parent"))
            if not ident or not pid or pid == "-":
                continue
            # 같은 사람이 여러 부서에 나올 수 있다. 식별자 단독을 키로 쓰면
            # 뒤에 온 것이 앞을 덮어 트리가 어긋난다. 부모까지 묶어서 키로 쓴다.
            key = (sc, f"{pid}\u0000{ident}")
            n = touch(key, ident, pid, r.fields.get(leaf.get("name", "")), "leaf")
            n["lastTs"] = r.ts
            continue

        if not cfg_tree.matches(r):
            continue
        ident = r.fields.get(cfg_tree.node)
        if not ident:
            continue
        # 최상위 노드는 식별자가 비어 있을 수 있다("-"). 버리면 "자식이 몇 개여야 하는지"
        # 같은 정보가 통째로 날아간다. 예약 id 를 주고 살린다.
        if ident == "-":
            ident = ROOT_ID
        pid = r.fields.get(cfg_tree.parent)
        if pid == "-" or pid == ident:
            pid = None

        n = touch((sc, ident), ident, pid, r.fields.get(cfg_tree.name) if cfg_tree.name else None, "node")
        n["lastTs"] = r.ts
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

    # 범위 필드가 없는 줄이 섞일 수 있다. 그대로 두면 빈 범위에 갇혀 부모를 못 찾는다.
    # 부모가 다른 범위에 **유일하게** 있으면 그 범위로 옮긴다. 여러 범위에 있으면
    # 애매하므로 건드리지 않는다 — 잘못 붙이는 것보다 고아로 두는 게 낫다.
    #
    # 앱이 사람 줄에도 범위를 달아 주면 이 보정은 발동하지 않는다. 그래도 남겨 둔다.
    # 범위 필드가 없던 시절 빌드로 뽑은 로그를 열 때 필요하다.
    if scope_f:
        scopes_of_id: Dict[str, set] = {}
        for (sc, ident), n in nodes.items():
            if n["kind"] == "node":
                scopes_of_id.setdefault(n["id"], set()).add(sc)

        def unique_scope(ident: str):
            """이 식별자가 딱 한 범위에만 있으면 그 범위. 애매하면 None."""
            cands = scopes_of_id.get(ident, set()) - {""}
            return next(iter(cands)) if len(cands) == 1 else None

        moved = []
        for key in list(nodes):
            sc, ident = key
            n = nodes[key]
            if sc or not n["parent"]:
                continue
            target = unique_scope(n["parent"])
            if target:
                moved.append((key, (target, ident)))
        for old, new in moved:
            if new in nodes:          # 이미 같은 자리에 있으면 합치지 않는다
                continue
            n = nodes.pop(old)
            n["scope"] = new[0]
            nodes[new] = n
            order[order.index(old)] = new

        # 생략 인원 수도 같이 옮긴다. 노드만 옮기면 아래 붙이기에서 부모를 못 찾아
        # "+N 생략" 이 조용히 사라진다.
        for key in list(truncated):
            sc, pid = key
            if sc:
                continue
            target = unique_scope(pid)
            if target:
                truncated[(target, pid)] = truncated.get((target, pid), 0) + truncated.pop(key)

    for (sc, pid), cnt in truncated.items():
        holder = nodes.get((sc, pid))
        if holder is not None:
            holder["truncated"] = cnt

    # 부모-자식 잇기. 같은 scope 안에서만 잇는다.
    roots: List[dict] = []
    orphans = 0
    for key in order:
        sc, _ = key
        n = nodes[key]
        p = nodes.get((sc, n["parent"])) if n["parent"] else None
        if p is not None and p is not n:
            p["children"].append(n)
        else:
            if n["parent"]:
                n["orphan"] = True      # 부모 이름은 아는데 그 줄을 못 봄
                orphans += 1
            roots.append(n)

    # 최상위 노드를 봤다면, 같은 scope 에서 부모 없는 나머지를 그 아래로 모은다.
    # `parent=-` 는 "부모 없음"이 아니라 "최상위의 자식"이라는 뜻이기 때문이다.
    final_roots: List[dict] = []
    by_scope: Dict[str, List[dict]] = {}
    for n in roots:
        by_scope.setdefault(n["scope"], []).append(n)
    for sc, group in by_scope.items():
        container = nodes.get((sc, ROOT_ID))
        if container is not None and len(group) > 1:
            adopted = [n for n in group if n is not container and not n.get("orphan")]
            container["children"] = adopted + container["children"]
            final_roots.append(container)
            final_roots += [n for n in group if n is not container and n.get("orphan")]
        else:
            final_roots += group

    _assign_depth(final_roots)

    # depth 는 parent 와 중복 정보다. 트리는 parent 로만 세우고, depth 는 **검증**에 쓴다.
    # 어긋나면 parent 필드가 잘못 들어오고 있다는 신호다 (실제로 한 번 겪었다).
    depth_mismatch = 0
    if cfg_tree.depth_field:
        for n in nodes.values():
            if n["loggedDepth"] is not None and n["loggedDepth"] != n.get("depth"):
                n["depthMismatch"] = True
                depth_mismatch += 1

    # 앱이 "자식 N개" 라고 한 것과 실제로 본 수의 차이.
    # 사람 노드는 부서 수에 안 들어가므로 빼고 센다.
    for n in nodes.values():
        kids = sum(1 for c in n["children"] if c["kind"] == "node")
        n["missing"] = max(0, n["expected"] - kids) if n["expected"] is not None else None

    return {
        "id": cfg_tree.id,
        "label": cfg_tree.label,
        "roots": final_roots,
        "nodeCount": len(nodes),
        "rootCount": len(final_roots),
        "orphanCount": orphans,
        "scopeCount": len(by_scope),
        "maxDepth": max((_max_depth(r) for r in final_roots), default=0),
        "missingTotal": sum(n["missing"] or 0 for n in nodes.values()),
        "truncatedTotal": sum(n["truncated"] for n in nodes.values()),
        "depthMismatch": depth_mismatch,
    }


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
