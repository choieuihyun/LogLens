"""예전 로그 이관 도우미 — 읽기 전용.

앱 소스의 예전 로그 호출(Log.d(TAG, "..." + x) 등)을 훑어 도메인별 이관 진척과
호출마다의 처리 제안을 낸다. 소스를 고치지 않는다. 제안·복사·IDE 로 열기까지만 한다.

이관은 "추가" 가 아니라 "교체" 다. 옮길 가치가 없는 줄(구분선, 테스트 흔적, 주석 처리된 로그)은
지우자고 제안하고, 남길 줄은 이벤트 이름 + 필드로 바꾸는 코드를 제안한다.
분류는 추정이므로 제안마다 이유(why)를 붙인다.

도메인은 파일 경로가 아니라 TAG 로 가른다. 설정의 탭마다 적힌 legacyTagPattern 이
이미 "이 태그는 이 도메인" 을 말하고 있다 — 뷰어의 미분류 탭과 같은 기준이 된다.
"""

from __future__ import annotations

import os
import re
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

from .callsites import _files
from .events import _call_text, _split_args, _lit

DEFAULT_CALLS = ["Log"]
_LEVELS = "v|d|i|w|e|wtf"

# 옮길 가치가 없는 줄의 흔적. 틀려도 "지우기 후보" 로 보일 뿐이다 (이유와 함께).
_NOISE = re.compile(r"(@@|##|xxx|!!!|\btest\b|테스트|^[\W_]*$)", re.I)
_FAILURE = re.compile(r"(fail|error|exception|timeout|실패|오류|에러|거부|denied)", re.I)
_SUCCESS = re.compile(r"(success|succeed|complete[d]?|성공|완료)", re.I)
# 변수 이름의 단어(카멜·밑줄로 나눈 것)로 판단한다. 글자 일부로 보면 className 이 ssn 에 걸린다.
# 마지막 단어가 크기·코드·키 같은 것이면 값 자체가 아니므로 뺀다 (bodySize, responseCode).
_SENSITIVE_WORDS = {"body", "content", "contents", "text", "password", "passwd", "pwd", "pass",
                    "token", "secret", "phone", "mobile", "email", "jumin", "ssn", "card",
                    "account", "birth", "birthday"}
_DUMP_WORDS = {"json", "xml", "raw", "dump", "packet", "payload", "body", "response", "record"}
_META_WORDS = {"size", "length", "len", "count", "code", "key", "id", "type", "no", "idx",
               "disposition", "name", "time", "status", "yn"}


def _words(name: str) -> List[str]:
    return [w.lower() for w in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", name)]


def is_sensitive(name: str) -> bool:
    w = _words(name)
    return bool(w) and w[-1] not in _META_WORDS and any(x in _SENSITIVE_WORDS for x in w)


def is_dump(name: str) -> bool:
    w = _words(name)
    return bool(w) and w[-1] not in _META_WORDS and any(x in _DUMP_WORDS for x in w)


_STOP = {"handle", "on", "the", "a", "an", "is", "get", "set", "call", "called", "method", "do",
         "xxx", "test", "log", "debug", "info", "data", "result", "value", "and", "to", "of", "in"}


def _is_commented(line: str, start: int) -> bool:
    i = line.find("//")
    return 0 <= i < start


def _split_plus(expr: str) -> List[str]:
    """문자열 이어붙이기를 조각으로. 문자열·괄호 안의 + 는 자르지 않는다."""
    parts, cur, depth, in_str, k = [], [], 0, None, 0
    while k < len(expr):
        ch = expr[k]
        if in_str:
            cur.append(ch)
            if ch == "\\" and k + 1 < len(expr):
                cur.append(expr[k + 1])
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
        elif ch == "+" and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        k += 1
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


_KT_TPL = re.compile(r"\$\{([^}]+)\}|\$([A-Za-z_][\w.]*)")


def parse_message(expr: str) -> Tuple[str, List[str]]:
    """메시지 식 → (글자 부분, 변수 식 목록). 자바 + 이어붙이기와 코틀린 $템플릿을 다 푼다."""
    text, vars_ = [], []
    for p in _split_plus(expr):
        s = _lit(p)
        if s is None:
            vars_.append(p)
            continue
        last = 0
        for m in _KT_TPL.finditer(s):
            text.append(s[last:m.start()])
            vars_.append((m.group(1) or m.group(2)).strip())
            last = m.end()
        text.append(s[last:])
    return "".join(text), vars_


_PASS = {"toString", "trim", "toJson", "toList", "orEmpty", "toInt", "toLong"}
_GENERIC = {"id", "key", "name", "type", "code", "value", "size", "length", "count", "no", "idx"}


def field_name(expr: str) -> str:
    """변수 식 → 필드 이름.

    sendRecord.getChatRoomKey() → chatRoomKey, tailXml.toString() → tailXml,
    session.getId() → sessionId, unread.size → unreadSize (흔한 이름은 앞 이름을 붙인다)
    """
    segs = [re.sub(r"\(.*?\)", "", x) for x in re.split(r"\s*[.?!]+\s*", expr.strip())]
    segs = [re.sub(r"\W", "", x) for x in segs if re.sub(r"\W", "", x)]
    segs = [re.sub(r"^(get|is)(?=[A-Z])", "", x) for x in segs]
    while len(segs) > 1 and segs[-1] in _PASS:
        segs.pop()
    if not segs:
        return "value"
    last = segs[-1][:1].lower() + segs[-1][1:]
    if last.lower() in _GENERIC and len(segs) > 1:
        prev = segs[-2][:1].lower() + segs[-2][1:]
        last = prev + last[:1].upper() + last[1:]
    return last


def _is_throwable_text(v: str) -> bool:
    return bool(re.search(r"(^|\.)(message|localizedMessage|getMessage\(\)|toString\(\)|"
                          r"getLocalizedMessage\(\))$|getStackTraceString\(", v.strip())) and \
        bool(re.match(r"^(e|ex|t|th|err|error|exception|throwable)\b", v.strip()))


def event_name(text: str, failure: bool, success: bool) -> str:
    """로그 문구 → 이벤트 이름 후보. requestChangeChatNoticeState failed → CHANGE_CHAT_NOTICE_STATE_FAIL"""
    head = re.split(r"[:=]", text, 1)[0]
    words = []
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9]*", head):
        for w in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", tok):
            lw = w.lower()
            if lw in _STOP or _FAILURE.match(lw) or _SUCCESS.match(lw):
                continue                      # failed / completed 도 뺀다 (접미사는 따로 붙인다)
            if lw in ("request", "req") and not words:
                continue
            words.append(w.upper())
    words = words[:4]
    if not words:
        return "TODO_EVENT"
    name = "_".join(words)
    if failure and not name.endswith("_FAIL"):
        name += "_FAIL"
    elif success and not name.endswith("_OK"):
        name += "_OK"
    return name


class Resolver:
    """TAG → 도메인. 설정의 탭 legacyTagPattern 과 같은 기준."""

    def __init__(self, cfg):
        self.tabs = [t for t in cfg.tabs if t._legacy_re is not None and t.domains]

    def domain(self, tag: Optional[str]) -> Optional[str]:
        if not tag:
            return None
        for t in self.tabs:
            if t._legacy_re.search(tag):
                return t.domains[0]
        return None


_TAG_DEF = [
    re.compile(r"\b(\w*TAG\w*)\s*(?::\s*String\s*)?=\s*\"([^\"]+)\""),
    re.compile(r"\b(\w*TAG\w*)\s*(?::\s*String\s*)?=\s*(\w+)(?:\.class)?\.(?:getSimpleName\(\)|simpleName)"),
    re.compile(r"\b(\w*TAG\w*)\s*(?::\s*String\s*)?=\s*(\w+)::class\.java\.simpleName"),
]


def _tags_in(lines: List[str]) -> Dict[str, str]:
    out = {}
    for ln in lines:
        for p in _TAG_DEF:
            m = p.search(ln)
            if m:
                out.setdefault(m.group(1), m.group(2))
    return out


def scan_file(rel: str, lines: List[str], calls: List[str], resolver: Resolver,
              lang: str, dom_expr: str, known_events: Dict[str, str]) -> List[dict]:
    pat = re.compile(r"\b(" + "|".join(re.escape(c) for c in calls) + r")\.(" + _LEVELS + r")\s*\(")
    tags = _tags_in(lines)
    stem = os.path.splitext(os.path.basename(rel))[0]
    out = []
    for i, ln in enumerate(lines):
        for m in pat.finditer(ln):
            commented = _is_commented(ln, m.start())
            call = _call_text(lines, i, m.end() - 1)
            args = _split_args(call) if call else []
            tag_expr = args[0] if args else ""
            tag = _lit(tag_expr) if _lit(tag_expr) is not None else tags.get(tag_expr.strip())
            domain = resolver.domain(tag) or resolver.domain(stem)
            item = {"line": i + 1, "level": m.group(2).upper().replace("WTF", "E"),
                    "call": f"{m.group(1)}.{m.group(2)}", "tag": tag or tag_expr,
                    "domain": domain, "code": (call and (m.group(0) + call[1:])) or ln.strip(),
                    "commented": commented}
            if commented:
                item.update(action="delete", kind="commented", why="주석 처리된 로그 — 이미 안 찍힌다. 지운다")
                out.append(item)
                continue
            out.append(_suggest(item, args, lang, dom_expr, known_events))
    return out


def _suggest(item: dict, args: List[str], lang: str, dom_expr: str, known: Dict[str, str]) -> dict:
    msg_expr = args[1] if len(args) > 1 else '""'
    throwable = args[2].strip() if len(args) > 2 and _lit(args[2]) is None else None
    text, vars_ = parse_message(msg_expr)
    # e.message 같은 것을 글자로 이어 붙였다면 예외를 통째로 넘기자고 제안한다 (err=/at= 가 붙는다)
    t_vars = [v for v in vars_ if _is_throwable_text(v)]
    if t_vars and not throwable:
        throwable = re.split(r"[.]", t_vars[0])[0]
    vars_ = [v for v in vars_ if v not in t_vars]

    failure = bool(_FAILURE.search(text)) or bool(throwable)
    success = bool(_SUCCESS.search(text)) and not failure
    sensitive = [v for v in vars_ if is_sensitive(field_name(v))]
    # 응답·레코드를 통째로 찍는 값. 기획서 교훈: 응답 JSON·XML 통째 덤프는 로그 금지 (토큰이 섞여 나간다)
    dumps = [v for v in vars_ if v not in sensitive and is_dump(field_name(v))]
    safe_vars = [v for v in vars_ if v not in sensitive and v not in dumps]
    item["sensitive"] = [field_name(v) for v in sensitive]
    item["dumps"] = [field_name(v) for v in dumps]

    if _NOISE.search(text) and not throwable and not failure:
        item.update(action="delete", kind="noise",
                    why="구분선·테스트 흔적처럼 보인다 — 옮길 정보가 없으면 지운다")
        return item

    # 레벨: 에러가 아닌데 E 로 찍은 것은 낮춘다 (확신 낮음)
    lvl = item["level"]
    why = []
    if throwable:
        kind = "exception"
        lvl = "E" if lvl in ("E",) else "W"
        why.append(f"예외({throwable})를 넘긴다 — err=/at= 필드가 자동으로 붙는다")
    elif failure:
        kind = "failure"
        lvl = "W" if lvl not in ("E", "W") else lvl
        why.append("실패 문구 — _FAIL 이벤트로. 실패 사유(reason)를 필드로 넣는다")
    elif vars_:
        kind = "dump"
        if lvl in ("E", "W"):
            why.append(f"{lvl} 로 찍었지만 에러가 아니다 — D 로 낮춘다 (확신 낮음)")
            lvl = "D"
        why.append("값 확인용 — 흐름에 필요한 값만 필드로 남기고 나머지는 지운다")
    else:
        kind = "trace"
        if lvl in ("E", "W"):
            why.append(f"{lvl} 로 찍었지만 에러가 아니다 — D 로 낮춘다 (확신 낮음)")
            lvl = "D"
        why.append("지나감 표시 — 흐름의 한 단계라면 이벤트로, 아니면 지운다")
    if sensitive:
        why.append("민감할 수 있는 값(" + ", ".join(item["sensitive"]) + ")은 필드로 넣지 않는다")
    if dumps:
        why.append("응답·레코드 통째(" + ", ".join(item["dumps"]) + ")는 넣지 않는다 — 필요한 값만 골라 필드로")

    evt = event_name(text, failure, success)
    if evt in known and known[evt] != item["domain"]:
        why.append(f"이벤트 이름 {evt} 가 {known[evt]} 도메인에 이미 있다 — 다른 이름을 고른다")
    fields = []
    seen = set()
    for v in safe_vars:
        k = field_name(v)
        if k in seen:
            continue
        seen.add(k)
        fields.append((k, v))
    if kind == "failure" and "reason" not in seen:
        fields.append(("reason", '"TODO"'))
    dom = dom_expr.replace("{domain}", item["domain"] or "???")
    args_out = [dom, f'"{evt}"'] + ([throwable] if throwable else [])
    if lang == "kt":
        args_out += [f'"{k}" to {v}' for k, v in fields]
    else:
        for k, v in fields:
            args_out += [f'"{k}"', v]
    code = f"LogLens.{lvl.lower()}(" + ", ".join(args_out) + ")" + ("" if lang == "kt" else ";")
    item.update(action="replace", kind=kind, event=evt, suggestLevel=lvl, suggestion=code,
                why=" · ".join(why))
    return item


def scan(source: Dict[str, object], mig: Dict[str, object], cfg,
         known_events: Dict[str, str]) -> Tuple[Dict[str, List[dict]], Optional[str]]:
    """파일 → 예전 로그 호출 목록. (결과, 오류)"""
    root = os.path.abspath(os.path.expanduser(str(source.get("root") or "")))
    if not source.get("root") or not os.path.isdir(root):
        return {}, f"소스 루트를 찾지 못했다: {root}"
    calls = [str(c) for c in (mig.get("calls") or DEFAULT_CALLS) if re.fullmatch(r"\w+", str(c))]
    dom_expr = str(mig.get("domainExpr") or "AppDomain.{domain}")
    resolver = Resolver(cfg)
    out: "OrderedDict[str, List[dict]]" = OrderedDict()
    for rel, lines in _files(root, list(source.get("include") or ["*.java", "*.kt"])):
        lang = "kt" if rel.endswith(".kt") else "java"
        items = scan_file(rel, lines, calls, resolver, lang, dom_expr, known_events)
        if items:
            out[rel] = items
    return out, None


def summarize(files: Dict[str, List[dict]], loglens_by_domain: Dict[str, int]) -> dict:
    by_dom: Dict[str, dict] = {}

    def slot(d):
        return by_dom.setdefault(d or "미분류", {"domain": d or "미분류", "legacy": 0, "commented": 0,
                                                "delete": 0, "sensitive": 0, "loglens": 0})
    for d, n in loglens_by_domain.items():
        slot(d)["loglens"] += n
    rows = []
    for rel, items in files.items():
        active = [x for x in items if not x["commented"]]
        doms = [x["domain"] for x in active if x["domain"]]
        main = max(set(doms), key=doms.count) if doms else None
        for x in items:
            s = slot(x["domain"])
            if x["commented"]:
                s["commented"] += 1
            else:
                s["legacy"] += 1
            if x.get("action") == "delete":
                s["delete"] += 1
            if x.get("sensitive"):
                s["sensitive"] += 1
        rows.append({"file": rel, "domain": main, "legacy": len(active),
                     "commented": len(items) - len(active),
                     "delete": sum(1 for x in items if x.get("action") == "delete"),
                     "sensitive": sum(1 for x in items if x.get("sensitive"))})
    rows.sort(key=lambda r: -r["legacy"])
    doms = sorted(by_dom.values(), key=lambda d: (d["domain"] == "미분류", d["domain"]))
    for d in doms:
        total = d["legacy"] + d["loglens"]
        d["percent"] = round(100 * d["loglens"] / total) if total else None
    return {"domains": doms, "files": rows,
            "totals": {k: sum(d[k] for d in doms) for k in ("legacy", "commented", "delete", "sensitive", "loglens")}}
