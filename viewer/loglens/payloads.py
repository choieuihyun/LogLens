"""원문(payload) — 요청·응답 본문을 통째로 실은 줄들을 모아 되살린다.

계약은 docs/RECORD_FORMAT.md 8절. 라이브러리(lib/core 의 Payload.kt)가 큰 본문을 여러 줄로
나눠 보낸다. 줄마다 온전한 구조화 레코드이고, 예약 필드가 어느 묶음의 몇 번째 조각인지 말해 준다.

    evt=ADDR_ADD_RES flowId=a1 plId=k31 plPart=1 plParts=2 plBytes=5120 | {"result":"ok","list":[...
    evt=ADDR_ADD_RES flowId=a1 plId=k31 plPart=2 plParts=2 plBytes=5120 | ...]}

여기서 하는 일은 둘이다.

1. **받는 즉시 모은다.** 로그 버퍼는 오래된 줄부터 밀려난다. 버퍼에서 조각을 찾아 합치면
   앞 조각이 밀려난 원문은 깨져 보인다. 그래서 조각은 따로 모아 두고, 버퍼에는 묶음마다
   한 줄(머리)만 남긴다. 통계·이슈·흐름이 조각 수만큼 부풀지 않는 것도 그 덕이다.
2. **빠진 조각을 숨기지 않는다.** logcat 은 줄을 잃을 수 있다. 받은 조각만 이어 붙이면 멀쩡한
   본문처럼 보인다. 어느 조각이 없는지 그대로 알려 준다.

본문을 JSON·XML 로 풀어 보여 주는 일은 브라우저가 한다 (web/app.js).
"""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Dict, List, Optional

from .parser import Record, STRUCTURED, TRUNCATION_MARK

F_ID = "plId"
F_PART = "plPart"
F_PARTS = "plParts"
F_BYTES = "plBytes"
F_CUT = "plCut"
F_ERR = "plErr"

# 세션 파일로 내보낼 때 원문을 뺐다는 표시 (plErr 의 값)
ERR_EXCLUDED = "excluded"

PREVIEW_CHARS = 160
# 모아 두는 묶음의 상한. 넘으면 오래된 묶음부터 버린다 (그 원문은 "밀려남" 으로 보인다).
MAX_ITEMS = 500
MAX_TOTAL_BYTES = 32 * 1024 * 1024
# 조각 수가 이보다 크다고 적힌 줄은 믿지 않는다 (64KB 상한이면 수십 개다)
MAX_PARTS = 5000

_ESC = re.compile(r"\\(u[0-9A-Fa-f]{4}|.)", re.S)
_SIMPLE = {"\\": "\\", "n": "\n", "r": "\r", "t": "\t", "s": " "}
# 내보낼 때 머리에서 조각 정보를 갈아 끼운다
_PL_FIELDS = re.compile(r" plPart=\d+ plParts=\d+ plBytes=\d+(?: plCut=\d+)?(?: plErr=\S+)?")


def is_reserved(key: str) -> bool:
    """pl 뒤에 대문자가 오는 이름은 라이브러리가 쓴다 (plId, plPart …). place 는 아니다."""
    return len(key) > 2 and key.startswith("pl") and "A" <= key[2] <= "Z"


def escape(chunk: str) -> str:
    """라이브러리의 Payload.escape 와 같은 규칙. 뷰어는 로그를 찍지 않지만 가짜 로그 생성기가 쓴다."""
    out = []
    last = len(chunk) - 1
    for i, ch in enumerate(chunk):
        cp = ord(ch)
        edge = i == 0 or i == last
        if ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif cp < 0x20 or 0x7F <= cp <= 0x9F or cp in (0x2028, 0x2029) or 0xD800 <= cp <= 0xDFFF:
            out.append("\\u%04X" % cp)
        elif edge and ch == " ":
            out.append("\\s")
        elif edge and ch.isspace():
            out.append("\\u%04X" % cp)
        else:
            out.append(ch)
    s = "".join(out)
    # 우연히 잘림 표시로 끝나면 잘린 줄로 보인다. 마지막 글자만 바꿔 둔다.
    return s[:-1] + "\\u005D" if s.endswith(TRUNCATION_MARK) else s


def unescape(s: str) -> str:
    """Payload.escape 의 반대. 모르는 이스케이프는 그대로 둔다 (파서는 관용적)."""
    if "\\" not in s:
        return s

    def sub(m: "re.Match") -> str:
        e = m.group(1)
        if len(e) == 5:
            return chr(int(e[1:], 16))
        return _SIMPLE.get(e, m.group(0))

    return _ESC.sub(sub, s)


def chunk_of(rec: Record) -> Optional[dict]:
    """원문 조각이면 그 정보를, 아니면 None. 숫자가 이상하면 원문으로 치지 않는다 (보통 줄로 남는다)."""
    if rec.kind != STRUCTURED or F_ID not in rec.fields:
        return None
    f = rec.fields
    try:
        part, parts, nbytes = int(f[F_PART]), int(f[F_PARTS]), int(f[F_BYTES])
        cut = int(f[F_CUT]) if F_CUT in f else None
    except (KeyError, ValueError):
        return None
    if not (1 <= part <= parts <= MAX_PARTS) or nbytes < 0:
        return None
    return {"id": f[F_ID], "part": part, "parts": parts, "bytes": nbytes, "cut": cut,
            "err": f.get(F_ERR), "text": unescape(rec.msg or "")}


def is_payload(rec: Record) -> bool:
    return chunk_of(rec) is not None


def key_of(rec: Record, pl_id: str) -> str:
    """묶음 키. 같은 id 라도 다른 프로세스(pid)면 다른 묶음이다."""
    return f"{rec.pid or 0}-{pl_id}"


def sniff(text: str) -> str:
    """본문의 첫 글자로 형식을 짐작한다. 확정은 브라우저가 실제로 풀어 보고 한다."""
    t = text.lstrip()[:1]
    if t in ("{", "["):
        return "json"
    if t == "<":
        return "xml"
    return "text"


def strip_body(raw: str) -> str:
    """원본 줄에서 본문을 뗀 머리. 버퍼에 남는 줄에는 본문이 없어야 이슈 규칙이 본문에 걸리지 않는다."""
    at = raw.find(" | ")
    return raw if at < 0 else raw[:at]


def excluded_line(raw: str) -> str:
    """세션 파일에 원문을 빼고 남길 한 줄. 다시 열면 "내보낼 때 뺐다" 로 보인다."""
    head = strip_body(raw)
    out, n = _PL_FIELDS.subn(f" plPart=1 plParts=1 plBytes=0 plErr={ERR_EXCLUDED}", head, count=1)
    return out if n else head


class PayloadStore:
    """받은 조각을 묶음별로 모은다. 스레드 보호는 부르는 쪽(Hub 의 락)이 한다."""

    def __init__(self, max_items: int = MAX_ITEMS, max_bytes: int = MAX_TOTAL_BYTES):
        self.max_items = max_items
        self.max_bytes = max_bytes
        self._items: "OrderedDict[str, dict]" = OrderedDict()
        self._bytes = 0

    def clear(self) -> None:
        self._items.clear()
        self._bytes = 0

    def __len__(self) -> int:
        return len(self._items)

    def add(self, rec: Record) -> Optional[dict]:
        """조각을 넣는다. 원문 조각이 아니면 None.

        돌려주는 것: {"key", "first"(이 묶음의 첫 줄인가), "info"(머리 줄에 실을 요약)}
        """
        c = chunk_of(rec)
        if c is None:
            return None
        key = key_of(rec, c["id"])
        e = self._items.get(key)
        # 조각 수나 크기가 다르면 같은 id 를 다시 쓴 다른 묶음이다 (앱 재시작 등). 새로 시작한다.
        if e is not None and (e["parts"] != c["parts"] or e["bytes"] != c["bytes"]):
            self._drop(key)
            e = None
        first = e is None
        if e is None:
            e = {
                "key": key, "id": c["id"], "pid": rec.pid,
                "domain": rec.domain, "event": rec.event, "level": rec.level, "tag": rec.tag,
                "ts": rec.ts, "lastTs": rec.ts,
                "fields": {k: v for k, v in rec.fields.items() if not is_reserved(k)},
                "parts": c["parts"], "bytes": c["bytes"], "cut": c["cut"], "err": c["err"],
                "got": {}, "raws": {}, "size": 0,
            }
            self._items[key] = e
        old = e["got"].get(c["part"])
        if old is not None:
            self._bytes -= len(old) + len(e["raws"][c["part"]])
            e["size"] -= len(old) + len(e["raws"][c["part"]])
        e["got"][c["part"]] = c["text"]
        e["raws"][c["part"]] = rec.raw
        e["lastTs"] = rec.ts
        add = len(c["text"]) + len(rec.raw)
        e["size"] += add
        self._bytes += add
        self._items.move_to_end(key)
        self._evict(keep=key)
        return {"key": key, "first": first, "info": self.info(key)}

    def _drop(self, key: str) -> None:
        e = self._items.pop(key, None)
        if e:
            self._bytes -= e["size"]

    def _evict(self, keep: str) -> None:
        while len(self._items) > 1 and (len(self._items) > self.max_items or self._bytes > self.max_bytes):
            oldest = next(iter(self._items))
            if oldest == keep:
                break
            self._drop(oldest)

    def info(self, key: str) -> Optional[dict]:
        """목록 한 줄에 실을 요약. 본문은 싣지 않는다 (미리보기 몇 글자만)."""
        e = self._items.get(key)
        if e is None:
            return None
        first = e["got"].get(1, "")
        return {"key": key, "parts": e["parts"], "bytes": e["bytes"], "cut": e["cut"], "err": e["err"],
                "format": sniff(first) if first else "text",
                "preview": first[:PREVIEW_CHARS]}

    def detail(self, key: str) -> Optional[dict]:
        """묶음 하나를 되살린다. 빠진 조각은 빈 자리로 남기고 번호를 알려 준다."""
        e = self._items.get(key)
        if e is None:
            return None
        segments: List[dict] = []
        missing: List[int] = []
        for n in range(1, e["parts"] + 1):
            t = e["got"].get(n)
            if t is None:
                missing.append(n)
                if segments and "missing" in segments[-1]:
                    segments[-1]["missing"].append(n)
                else:
                    segments.append({"missing": [n]})
            elif segments and "text" in segments[-1]:
                segments[-1]["text"] += t
            else:
                segments.append({"text": t})
        text = "".join(s.get("text", "") for s in segments)
        got_bytes = len(text.encode("utf-8", "surrogatepass"))
        complete = not missing
        return {
            "key": key, "id": e["id"], "pid": e["pid"],
            "domain": e["domain"], "event": e["event"], "level": e["level"], "tag": e["tag"],
            "ts": e["ts"], "lastTs": e["lastTs"], "fields": e["fields"],
            "parts": e["parts"], "received": e["parts"] - len(missing), "missing": missing,
            "bytes": e["bytes"], "gotBytes": got_bytes, "cut": e["cut"], "err": e["err"],
            "complete": complete,
            # 다 받았는데 크기가 다르면 되살린 본문을 믿을 수 없다 (형식이 어긋났다는 뜻)
            "sizeMismatch": complete and got_bytes != e["bytes"],
            "format": sniff(text),
            "text": text, "segments": segments,
        }

    def raw_lines(self, key: str) -> List[str]:
        """받은 원본 줄을 조각 순서대로 (세션 파일에 원문까지 담을 때)."""
        e = self._items.get(key)
        if e is None:
            return []
        return [e["raws"][n] for n in sorted(e["raws"])]
