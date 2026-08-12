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
