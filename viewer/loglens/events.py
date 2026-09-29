"""이벤트 목록 — 커버리지와 사전.

앱 소스의 LogLens 호출을 훑어 "앱이 찍을 수 있는 이벤트 전부" 와 이벤트마다 싣는 필드를 만든다.
여기에 뷰어가 실제로 받은 로그를 겹치면:
  - 커버리지: 이번에 한 번도 안 지나간 이벤트 (= 안 탄 코드 경로)
  - 사전:     이벤트별 필드, 찍는 곳, 실제로 온 값
  - 이름 검사: 같은 뜻 다른 표기, 실패 사유 없는 실패 이벤트 등 (분석이 쪼개지는 원인)

호출 인자는 쉼표로 자르지 않고 토큰을 나눈다. 문자열 안의 쉼표("로그인 성공, 다음"),
중첩 호출, 여러 줄에 걸친 호출이 있어서 단순히 자르면 없는 필드가 생긴다.
"""

from __future__ import annotations

import os
import re
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

from .callsites import _COMMENT_LINE, _DEFAULT_INCLUDE, _enclosing_method, _files

_CALL = re.compile(r"\bLogLens\.([vdiwe])\s*\(")
_STR = re.compile(r'^"((?:[^"\\]|\\.)*)"$')
_UPPER_SNAKE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")
_MAX_CALL_LINES = 20
# 라이브러리(Formatter)가 정한 것. 바뀌면 같이 바꾼다.
MSG_KEY = "msg"
THROWABLE_KEYS = ("err", "at")


def _call_text(lines: List[str], i: int, start: int) -> Optional[str]:
    """i 줄 start 칸의 '(' 부터 짝이 맞는 ')' 까지. 문자열·문자 리터럴 안의 괄호는 세지 않는다."""
    depth = 0
    out = []
    in_str = None
    for j in range(i, min(len(lines), i + _MAX_CALL_LINES)):
        ln = lines[j][start:] if j == i else lines[j]
        k = 0
        while k < len(ln):
            ch = ln[k]
            if in_str:
                if ch == "\\":
                    out.append(ln[k:k + 2])
                    k += 2
                    continue
                if ch == in_str:
                    in_str = None
            elif ch in "\"'":
                in_str = ch
            elif ch == "/" and ln[k:k + 2] == "//":
                break                                   # 줄 끝 주석
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth == 0:
                    out.append(ch)
                    return "".join(out)
            out.append(ch)
            k += 1
        out.append(" ")
    return None


def _split_args(call: str) -> List[str]:
    """'(a, "b, c", f(x, y))' → ['a', '"b, c"', 'f(x, y)']"""
    body = call[1:-1]
    args, cur, depth, in_str = [], [], 0, None
    k = 0
    while k < len(body):
        ch = body[k]
        if in_str:
            cur.append(ch)
            if ch == "\\" and k + 1 < len(body):
                cur.append(body[k + 1])
                k += 2
                continue
            if ch == in_str:
                in_str = None
        elif ch in "\"'":
            in_str = ch
            cur.append(ch)
        elif ch in "([{":
            depth += 1
            cur.append(ch)
        elif ch in ")]}":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        k += 1
    if "".join(cur).strip():
        args.append("".join(cur).strip())
    return args


def _lit(a: str) -> Optional[str]:
    m = _STR.match(a.strip())
    return m.group(1) if m else None


def _kt_pair_key(a: str) -> Optional[str]:
    m = re.match(r'^"((?:[^"\\]|\\.)*)"\s+to\s+', a.strip())
    return m.group(1) if m else None


def parse_call(args: List[str]) -> Optional[Tuple[str, str, List[str]]]:
    """(도메인, 이벤트, 필드 키) — 이벤트가 문자열 리터럴이 아니면 None (동적 이름은 셀 수 없다)."""
    if len(args) < 2:
        return None
    event = _lit(args[1])
    if event is None:
        return None
    dom_expr = args[0].strip()
    m = re.search(r"([A-Za-z0-9_]+)\s*$", dom_expr)
    domain = m.group(1).upper() if m and re.fullmatch(r"[A-Z0-9_]+", m.group(1)) else "기타"
    rest = args[2:]
    keys: List[str] = []
    throwable = False
    if any(_kt_pair_key(a) for a in rest):
        # 코틀린 "k" to v. 예외는 쌍이 아닌 첫 인자로 온다 (LogLens.e(d, "E", ex, "k" to v))
        if rest and not _kt_pair_key(rest[0]) and _lit(rest[0]) is None:
            throwable = True
        keys = [k for k in (_kt_pair_key(a) for a in rest) if k]
    else:
        # 자바 가변 인자: 예외 인자가 앞에 올 수 있다 (LogLens.e(d, "E", ex, "k", v))
        if rest and _lit(rest[0]) is None and len(rest) % 2 == 1:
            rest = rest[1:]
            throwable = True
        keys = [k for k in (_lit(a) for a in rest[0::2]) if k is not None]
    # 라이브러리 규칙: msg 는 필드가 아니라 "| " 뒤 자유 메시지, 예외는 err= / at= 로 접혀 들어간다
    keys = [k for k in keys if k != MSG_KEY]
    if throwable:
        keys += [k for k in THROWABLE_KEYS if k not in keys]
    return domain, event, keys


def inventory(source: Dict[str, object]) -> Tuple[List[dict], Optional[str]]:
    """앱 소스에서 이벤트 목록. (목록, 오류) — 예외를 던지지 않는다."""
    root = os.path.abspath(os.path.expanduser(str(source.get("root") or "")))
    if not source.get("root") or not os.path.isdir(root):
        return [], f"소스 루트를 찾지 못했다: {root}"
    include = list(source.get("include") or _DEFAULT_INCLUDE)
    found: "OrderedDict[str, dict]" = OrderedDict()
    for rel, lines in _files(root, include):
        for i, ln in enumerate(lines):
            if _COMMENT_LINE.match(ln):
                continue
            for m in _CALL.finditer(ln):
                call = _call_text(lines, i, m.end() - 1)
                parsed = parse_call(_split_args(call)) if call else None
                if not parsed:
                    continue
                domain, event, keys = parsed
                e = found.setdefault(event, {"event": event, "domains": [], "levels": [],
                                             "emits": [], "declared": []})
                if domain not in e["domains"]:
                    e["domains"].append(domain)
                lvl = m.group(1).upper()
                if lvl not in e["levels"]:
                    e["levels"].append(lvl)
                e["emits"].append({"where": f"{rel}:{i + 1}", "method": _enclosing_method(lines, i)})
                for k in keys:
                    if k not in e["declared"]:
                        e["declared"].append(k)
    return list(found.values()), None


class Seen:
    """뷰어가 받은 구조화 로그의 누적. 버퍼가 밀려나도 줄지 않는다 (커버리지는 버퍼 크기와 무관해야)."""

    def __init__(self):
        self.clear()

    def clear(self):
        self.events: Dict[str, dict] = {}

    def observe(self, rec) -> None:
        e = self.events.get(rec.event)
        if e is None:
            e = self.events[rec.event] = {"count": 0, "domains": [], "fields": OrderedDict(),
                                          "firstTs": rec.ts, "lastTs": rec.ts}
        e["count"] += 1
        e["lastTs"] = rec.ts
        if rec.domain not in e["domains"]:
            e["domains"].append(rec.domain)
        for k, v in rec.fields.items():
            if k not in e["fields"]:
                e["fields"][k] = v                      # 처음 본 값을 예시로 남긴다
        if rec.msg and "msg" not in e["fields"]:
            e["fields"]["msg"] = rec.msg


def build(inv: List[dict], seen: Dict[str, dict], outcome, synonyms: List[List[str]]) -> dict:
    """소스 목록과 받은 로그를 합치고 이름 검사를 한다."""
    by = OrderedDict()
    for e in inv:
        by[e["event"]] = dict(e, seen=0, observed=[], example={}, lastTs=None, inSource=True)
    for name, s in seen.items():
        e = by.get(name)
        if e is None:
            e = by[name] = {"event": name, "domains": list(s["domains"]), "levels": [], "emits": [],
                            "declared": [], "inSource": False}
        e["seen"] = s["count"]
        e["lastTs"] = s["lastTs"]
        e["observed"] = [k for k in s["fields"] if k != "msg"]
        e["example"] = dict(s["fields"])
    events = list(by.values())
    for e in events:
        e["domain"] = e["domains"][0] if e["domains"] else "기타"
    return {"events": events, "lint": lint(events, outcome, synonyms)}


def _norm(k: str) -> str:
    return k.replace("_", "").replace("-", "").lower()


def lint(events: List[dict], outcome, synonyms: List[List[str]]) -> List[dict]:
    out = []
    # 필드 이름: 대소문자·밑줄만 다른 표기 (userId / user_id / UserId)
    spell: Dict[str, Dict[str, List[str]]] = {}
    for e in events:
        for k in set(e["declared"]) | set(e.get("observed") or []):
            spell.setdefault(_norm(k), {}).setdefault(k, []).append(e["event"])
    for _, variants in sorted(spell.items()):
        if len(variants) > 1:
            names = sorted(variants)
            out.append({"level": "warn", "kind": "field-spelling",
                        "message": f"같은 필드를 다르게 적음: {' / '.join(names)}",
                        "fields": names,
                        "events": sorted({ev for v in variants.values() for ev in v})})
    # 설정에 적은 동의어 (uid / userId 처럼 표기로는 못 잡는 것)
    for group in synonyms or []:
        used = {k: sorted({e["event"] for e in events
                           if k in e["declared"] or k in (e.get("observed") or [])}) for k in group}
        hit = [k for k, evs in used.items() if evs]
        # 표기만 다른 묶음(roomId / room_id)은 위에서 이미 알렸다. 같은 경고를 두 번 내지 않는다.
        if len(hit) > 1 and len({_norm(k) for k in hit}) > 1:
            out.append({"level": "warn", "kind": "field-synonym",
                        "message": f"같은 뜻 다른 이름: {' / '.join(hit)}", "fields": hit,
                        "events": sorted({ev for k in hit for ev in used[k]})})
    names = {e["event"] for e in events}
    for e in events:
        ev = e["event"]
        if not _UPPER_SNAKE.match(ev):
            out.append({"level": "warn", "kind": "event-name", "events": [ev],
                        "message": f"이벤트 이름이 대문자_밑줄 형식이 아님: {ev}"})
        kind = outcome.classify(ev)
        if kind == "success":
            stem = next(ev[:-len(s)] for s in outcome.success if ev.endswith(s))
            if not any(stem + f in names for f in outcome.failure):
                out.append({"level": "info", "kind": "no-failure-pair", "events": [ev],
                            "message": f"{ev} 의 실패 짝(_FAIL 등)이 없음 — 성공률을 낼 수 없다"})
        if kind == "failure":
            fields = set(e["declared"]) | set(e.get("observed") or [])
            if fields and not (fields & set(outcome.reason_fields)):
                out.append({"level": "warn", "kind": "no-reason", "events": [ev],
                            "message": f"{ev} 에 실패 사유 필드({'/'.join(outcome.reason_fields)})가 없음 — 실패 사유 분포에서 빠진다"})
        if len(e["domains"]) > 1:
            out.append({"level": "info", "kind": "multi-domain", "events": [ev],
                        "message": f"{ev} 를 여러 도메인에서 찍음: {', '.join(e['domains'])}"})
        if e.get("seen") and not e.get("inSource", True):
            out.append({"level": "info", "kind": "not-in-source", "events": [ev],
                        "message": f"{ev} 가 로그에는 왔지만 소스에서 못 찾음 (다른 모듈·옛 빌드·동적 이름)"})
    return out
