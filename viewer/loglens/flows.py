"""흐름(flowId) 하나를 따라간다 — 타임라인과 기준선 비교.

로그인 한 번이 실패하면 제일 먼저 묻는 것은 "어디서 멈췄나" 와 "어느 단계가 느렸나" 다.
flowId 로 이어진 줄을 시간순으로 세우고, 단계 사이 간격과 그 시간대에 끼어 있던
다른 로그(네트워크 에러 등)를 같이 보여준다.

기준선: 정상적으로 끝난 흐름 하나를 저장해 두고, 같은 종류의 흐름을 그것과 견준다.
룰 비교가 "설정이 달라졌나" 라면 이건 "동작이 달라졌나" 다.

logcat 시각에는 연도가 없다(MM-DD HH:MM:SS.mmm). 간격만 필요하므로 가상의 연도를 붙이고,
자정·연말을 넘어 음수가 나오면 하루/일 년을 더한다.
"""

from __future__ import annotations

import datetime
import json
import os
import re
from collections import OrderedDict
from typing import Dict, List, Optional

from .parser import Record, STRUCTURED

# 느림 판정: 비율과 절대 차이를 둘 다 넘어야 한다. 1ms→3ms 를 느리다고 하면 소음이 된다.
SLOW_RATIO = 2.0
SLOW_GAP_MS = 200
# 마지막 로그가 버퍼의 최신 로그보다 이만큼 오래됐는데 안 끝났으면 "진행 중" 이 아니라 "멈춤"
STALL_MS = 30_000
CONTEXT_MAX = 30

_TS_SHORT = re.compile(r"^(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)\.(\d{3})$")
_TS_LONG = re.compile(r"^(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)\.(\d{3})$")


def ts_ms(ts: Optional[str]) -> Optional[int]:
    """로그 시각 → 밀리초. 모르는 형식이면 None."""
    if not ts:
        return None
    m = _TS_LONG.match(ts)
    if m:
        y, mo, d, h, mi, s, ms = (int(x) for x in m.groups())
    else:
        m = _TS_SHORT.match(ts)
        if not m:
            return None
        y = 2000                                   # 윤년이라 02-29 도 받는다
        mo, d, h, mi, s, ms = (int(x) for x in m.groups())
    try:
        t = datetime.datetime(y, mo, d, h, mi, s, ms * 1000)
    except ValueError:
        return None
    return int(t.timestamp() * 1000)


def _gap(a: Optional[int], b: Optional[int]) -> Optional[int]:
    """a → b 간격.

    날짜(MM-DD)가 로그에 있으므로 자정 넘김은 그냥 맞는다. 연도가 없어서 틀리는 것은 연말뿐이다
    (12-31 → 01-01 이 가상의 같은 해에서는 거꾸로 간다). 그때만 1년을 더한다.
    가상의 해는 2000년(윤년, 366일)이므로 366일을 더한다.
    """
    if a is None or b is None:
        return None
    g = b - a
    if g < -3_600_000:
        g += 366 * 86_400_000
    return g


class FlowSpec:
    """흐름을 찾는 설정. 기본은 flowId 로 잇고 uid 를 이름으로 쓴다."""

    def __init__(self, cfg):
        f = getattr(cfg, "flow", None) or {}
        self.field = str(f.get("field") or "flowId")
        # 이름 필드는 여럿을 적을 수 있다. 앞에서부터 값이 있는 것을 쓴다 (예: ["uid", "type"])
        lf = f.get("labelField") or "uid"
        self.label_fields = [str(x) for x in (lf if isinstance(lf, list) else [lf])]
        self.cfg = cfg

    def label(self, recs: List[Record]) -> Optional[str]:
        for fld in self.label_fields:
            for r in recs:
                if r.fields.get(fld):
                    return r.fields[fld]
        return None

    def table_of(self, rec: Record):
        for t in self.cfg.tables:
            if t.matches(rec):
                return t
        return None


def _outcome(cfg, recs: List[Record]) -> str:
    kinds = [cfg.outcome.classify(r.event) for r in recs]
    if "failure" in kinds or any(r.level == "E" for r in recs):
        return "failure"
    if kinds and kinds[-1] == "success":
        return "success"
    return "open"


def _group(records: List[Record], spec: FlowSpec) -> "OrderedDict[str, List[int]]":
    """flowId → 버퍼 안의 위치 목록."""
    out: "OrderedDict[str, List[int]]" = OrderedDict()
    for i, r in enumerate(records):
        if r.kind == STRUCTURED:
            fid = r.fields.get(spec.field)
            if fid:
                out.setdefault(fid, []).append(i)
    return out


def _latest_ms(records: List[Record]) -> Optional[int]:
    for r in reversed(records):
        t = ts_ms(r.ts)
        if t is not None:
            return t
    return None


def _kind(cfg, recs: List[Record]) -> str:
    """흐름의 종류. 기준선을 이 이름으로 찾는다.

    흐름 안에서 퍼널 단계에 해당하는 첫 이벤트로 정한다. 첫 이벤트만 보면, 퍼널 앞에 붙는
    선택 단계(예: 새 방일 때만 오는 키 발급)로 시작하는 흐름이 다른 종류로 갈라진다.
    """
    for r in recs:
        for f in cfg.funnels:
            if r.event in f.steps:
                return f.id
    return (recs[0].event if recs else "") or "?"


def _steps(recs: List[Record], spec: FlowSpec) -> List[dict]:
    """흐름의 단계. 표로 묶이는 이벤트(설정 목록 등)가 연달아 오면 한 단계로 접는다."""
    steps: List[dict] = []
    prev_ms = None
    for r in recs:
        t = spec.table_of(r)
        if t and steps and steps[-1]["event"] == r.event and steps[-1].get("table"):
            steps[-1]["count"] += 1
            steps[-1]["lastTs"] = r.ts
            prev_ms = ts_ms(r.ts) or prev_ms
            continue
        now = ts_ms(r.ts)
        steps.append({
            "event": r.event, "domain": r.domain, "level": r.level, "ts": r.ts, "lastTs": r.ts,
            "delta": _gap(prev_ms, now) if steps else 0,
            "fields": {k: v for k, v in r.fields.items() if k != spec.field},
            "msg": r.msg, "count": 1, "table": t.id if t else None,
            "outcome": spec.cfg.outcome.classify(r.event),
        })
        prev_ms = now if now is not None else prev_ms
    return steps


def list_flows(records: List[Record], cfg, baselines: Optional[dict] = None) -> List[dict]:
    spec = FlowSpec(cfg)
    latest = _latest_ms(records)
    out = []
    for fid, idxs in _group(records, spec).items():
        recs = [records[i] for i in idxs]
        first_ms, last_ms = ts_ms(recs[0].ts), ts_ms(recs[-1].ts)
        oc = _outcome(cfg, recs)
        age = _gap(last_ms, latest)
        status = oc if oc != "open" else ("stalled" if age is not None and age > STALL_MS else "open")
        label = spec.label(recs)
        steps = _steps(recs, spec)
        kind = _kind(cfg, recs)
        dev = None
        if baselines and kind in baselines:
            dev = compare(steps, baselines[kind], status)["summary"]
            # 목록에서 "기준선과 다름" 으로 띄울지. 실패한 흐름은 성공 단계가 빠지고 실패 단계가 끼어
            # 늘 다르다 — 그건 "실패" 로 이미 보인다. 실패 흐름은 느림·순서 바뀜일 때만 띄운다.
            # 그래야 "성공은 했는데 느려진 흐름" 이 실패들에 묻히지 않는다. 전체 비교는 타임라인에 있다.
            dev["flag"] = (not dev["ok"]) if status == "success" else bool(dev["slow"] or dev["reordered"])
        out.append({
            "id": fid, "label": label, "kind": kind, "status": status,
            "firstTs": recs[0].ts, "lastTs": recs[-1].ts,
            "durationMs": _gap(first_ms, last_ms), "ageMs": age,
            "steps": len(steps), "lastEvent": recs[-1].event, "domain": recs[0].domain,
            "deviation": dev,
        })
    return out


def flow_detail(records: List[Record], cfg, fid: str, baselines: Optional[dict] = None) -> Optional[dict]:
    spec = FlowSpec(cfg)
    groups = _group(records, spec)
    if fid not in groups:
        return None
    idxs = groups[fid]
    recs = [records[i] for i in idxs]
    steps = _steps(recs, spec)
    first_ms, last_ms = ts_ms(recs[0].ts), ts_ms(recs[-1].ts)
    oc = _outcome(cfg, recs)
    latest = _latest_ms(records)
    age = _gap(last_ms, latest)
    status = oc if oc != "open" else ("stalled" if age is not None and age > STALL_MS else "open")

    # 그 시간대에 끼어 있던 다른 로그 — 경고·에러만. 흐름 밖 원인(네트워크 등)을 여기서 본다.
    ctx = []
    in_flow = set(idxs)
    lo, hi = idxs[0], idxs[-1]
    tail = hi
    # 흐름이 끝난 직후 잠깐까지 본다 (실패 원인이 실패 로그 바로 뒤에 찍히는 경우)
    while tail + 1 < len(records) and (_gap(last_ms, ts_ms(records[tail + 1].ts)) or 0) <= 1000:
        tail += 1
    # 같은 프로세스의 것만. 실제 기기의 logcat 에는 다른 앱·시스템 서비스의 경고가 끊임없이 섞인다.
    pids = {r.pid for r in recs if r.pid is not None}
    counts = {"W": 0, "E": 0}
    for i in range(lo, tail + 1):
        r = records[i]
        if i in in_flow or r.level not in ("W", "E"):
            continue
        if pids and r.pid not in pids:
            continue
        if r.kind == STRUCTURED and r.fields.get(spec.field):
            continue                               # 다른 흐름의 줄
        counts[r.level] += 1
        # 에러를 먼저 채운다. 경고가 많은 앱이면 경고가 상한을 먹어 에러가 안 보일 수 있다.
        if r.level == "E" or sum(1 for c in ctx if c["level"] == "W") < CONTEXT_MAX:
            ctx.append({"ts": r.ts, "level": r.level, "tag": r.tag, "text": r.msg or r.raw,
                        "offset": _gap(first_ms, ts_ms(r.ts))})

    # 누적 시간은 간격의 합이 아니라 시작부터 직접 잰다. 접힌 묶음 안의 시간이 빠지지 않게.
    for s in steps:
        s["offset"] = _gap(first_ms, ts_ms(s["ts"]))

    # 퍼널에 적힌 단계 중 안 온 것
    kind = _kind(cfg, recs)
    missing = []
    for f in cfg.funnels:
        if f.id == kind:
            seen = {s["event"] for s in steps}
            missing = [e for e in f.steps if e not in seen]

    d = {
        "id": fid, "kind": kind, "status": status, "label": spec.label(recs),
        "firstTs": recs[0].ts, "lastTs": recs[-1].ts, "durationMs": _gap(first_ms, last_ms),
        "ageMs": age, "steps": steps, "context": ctx[:CONTEXT_MAX * 2], "missing": missing,
        "contextCounts": counts,
        "baseline": None, "compare": None,
    }
    if baselines and kind in baselines:
        d["baseline"] = {k: baselines[kind][k] for k in ("flowId", "label", "savedAt", "durationMs")
                         if k in baselines[kind]}
        d["compare"] = compare(steps, baselines[kind], status)
    return d


def compare(steps: List[dict], base: dict, status: str) -> dict:
    """기준선과 견준다. 이벤트 이름 단위 — 같은 이벤트가 여러 번이면 첫 번째끼리."""
    bsteps = base.get("steps") or []
    bdelta = {}
    for b in bsteps:
        bdelta.setdefault(b["event"], b.get("delta"))
    cur = [s["event"] for s in steps]
    per = []
    slow = 0
    seen = set()
    for s in steps:
        e = s["event"]
        if e in seen:
            per.append({"event": e, "state": "same"})
            continue
        seen.add(e)
        if e not in bdelta:
            per.append({"event": e, "state": "extra"})
            continue
        b, c = bdelta[e], s.get("delta")
        is_slow = (b is not None and c is not None and c > b * SLOW_RATIO and c - b > SLOW_GAP_MS)
        slow += is_slow
        per.append({"event": e, "state": "slow" if is_slow else "same", "base": b, "cur": c,
                    "ratio": round(c / b, 1) if (b and c is not None) else None})
    # 기준선엔 있는데 없는 단계. 아직 진행 중인 흐름은 뒤쪽이 "안 온" 게 아니라 "아직" 이다.
    base_events = [b["event"] for b in bsteps]
    missing = [e for e in base_events if e not in cur]
    if status == "open":
        missing = []
    common_cur = [e for e in dict.fromkeys(cur) if e in bdelta]
    common_base = [e for e in dict.fromkeys(base_events) if e in set(cur)]
    reordered = common_cur != common_base
    extra = sum(1 for p in per if p["state"] == "extra")
    return {"steps": per, "missing": missing, "reordered": reordered,
            "summary": {"slow": slow, "missing": len(missing), "extra": extra,
                        "reordered": reordered,
                        "ok": not (slow or missing or extra or reordered)}}


class BaselineStore:
    """흐름 종류별 기준선 하나. 스냅샷 폴더 아래 baselines/ 에 둔다."""

    def __init__(self, root: str):
        self.dir = os.path.join(os.path.abspath(os.path.expanduser(root)), "baselines")

    def _path(self, kind: str) -> str:
        return os.path.join(self.dir, re.sub(r"[^A-Za-z0-9_.-]", "_", kind) + ".json")

    def save(self, detail: dict) -> bool:
        try:
            os.makedirs(self.dir, exist_ok=True)
            body = {"kind": detail["kind"], "flowId": detail["id"], "label": detail.get("label"),
                    "durationMs": detail.get("durationMs"),
                    "savedAt": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                    "steps": [{"event": s["event"], "delta": s.get("delta"), "count": s.get("count")}
                              for s in detail["steps"]]}
            tmp = self._path(detail["kind"]) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(body, f, ensure_ascii=False)
            os.replace(tmp, self._path(detail["kind"]))
            return True
        except (OSError, KeyError, TypeError, ValueError):
            return False

    def clear(self, kind: str) -> bool:
        try:
            os.remove(self._path(kind))
            return True
        except OSError:
            return False

    def all(self) -> Dict[str, dict]:
        out = {}
        if not os.path.isdir(self.dir):
            return out
        for fn in os.listdir(self.dir):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.dir, fn), encoding="utf-8") as f:
                    b = json.load(f)
                out[b["kind"]] = b
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return out
