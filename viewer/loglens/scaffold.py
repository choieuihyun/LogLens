"""config.json 자동 생성 — "어느 프로젝트에나"의 실무적 절반.

도메인 탭을 손으로 적는 건 마찰이다. 특히 **아직 이관을 시작하지 않은** 프로젝트에서는
무슨 도메인을 적어야 할지조차 모른다. 그래서 실제 로그를 표본으로 읽어 초안을 만든다.

두 가지 모드가 자동으로 섞인다:

* **이관된 부분** — `<PREFIX>_<DOMAIN>` 태그가 보이면 그 도메인으로 탭을 만든다.
* **아직인 부분** — 대상 앱 pid 가 찍은 레거시 태그를 이름으로 군집화해서
  `legacyTagPattern` 탭 초안을 만든다. 이관 전에도 화면이 정리돼 보이고,
  call site 를 하나씩 옮길 때마다 같은 탭이 구조화 레코드로 채워진다.

**개인정보:** 태그 이름과 빈도만 읽는다. 메시지 본문은 집계에도, 출력에도 쓰지 않는다.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional

from .parser import Record, STRUCTURED

# 앱이 아니라 플랫폼/벤더가 찍는 태그. pid 필터가 대부분 걸러주지만,
# pid 를 모를 때(패키지 미지정)를 위한 2차 방어선.
SYSTEM_TAG_RE = re.compile(
    r"^(wpa_supplicant|cnss|io_stats|sensors|Wifi|Sem|VSync|Render|Layer|SDM|"
    r"Connectivity|Freecess|OpenNetworkQos|CpEventLog|ActivityManager|"
    r"ActivityTaskManager|WindowManager|PackageManager|art|libc|DEBUG|"
    r"Zygote|dalvikvm|System\.err|StrictMode|Choreographer|OpenGLRenderer|"
    r"BufferQueue|SurfaceFlinger|audio|Camera|GED|ViewRootImpl|InputMethod)",
    re.IGNORECASE,
)

# 클래스 이름 꼬리표. 태그 군집화 전에 떼어낸다: ChatListFragment → ChatList
SUFFIXES = ("Fragment", "Activity", "Manager", "Service", "Adapter", "ViewModel",
            "Presenter", "Repository", "Repo", "Task", "Worker", "Helper",
            "Controller", "Handler", "Client", "Impl", "Util", "Utils")

MIN_LINES_FOR_TAB = 5     # 이보다 적게 찍힌 군집은 탭으로 만들지 않는다
MAX_TABS = 8


class LogLandscape:
    """표본에서 태그 지형을 모은다. 태그 이름과 개수만."""

    def __init__(self, prefix: str = "APP", app_pid: Optional[int] = None):
        self.prefix = prefix
        self.app_pid = app_pid
        self.domains: Counter = Counter()
        self.events: Dict[str, Counter] = defaultdict(Counter)
        self.legacy_tags: Counter = Counter()
        self.other_tags: Counter = Counter()
        self.total = 0
        self.structured = 0
        self.pids: Counter = Counter()

    def observe(self, rec: Record) -> None:
        if rec.tag is None:
            return
        self.total += 1
        if rec.pid:
            self.pids[rec.pid] += 1

        if rec.kind == STRUCTURED and rec.domain:
            self.structured += 1
            self.domains[rec.domain] += 1
            self.events[rec.domain][rec.event] += 1
            return

        # 우리 앱이 찍은 게 아니면 레거시 후보에서 뺀다
        if self.app_pid is not None and rec.pid != self.app_pid:
            self.other_tags[rec.tag] += 1
            return
        if self.app_pid is None and SYSTEM_TAG_RE.match(rec.tag):
            self.other_tags[rec.tag] += 1
            return
        self.legacy_tags[rec.tag] += 1

    # -- 군집화 --------------------------------------------------------------
    @staticmethod
    def stem(tag: str) -> str:
        """ChatListFragment → CHAT,  DBLog → DBLOG,  NotificationTask → NOTIFICATION"""
        t = tag.split(".")[-1].strip("_")
        for s in SUFFIXES:
            if len(t) > len(s) + 2 and t.endswith(s):
                t = t[: -len(s)]
                break
        # camelCase 첫 토큰
        parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+", t)
        head = (parts[0] if parts else t).upper()
        # 머리글자만 남는 경우(DBLog → DB)는 정보가 없다. 두 토큰을 붙인다.
        if len(head) <= 2 and len(parts) > 1:
            head = (parts[0] + parts[1]).upper()
        # 단수/복수를 합친다: Chats 와 ChatListFragment 가 다른 탭이 되면 안 된다
        if len(head) > 4 and head.endswith("S") and not head.endswith("SS"):
            head = head[:-1]
        return head

    def clusters(self) -> List[tuple]:
        """(stem, [tags], line_count) — 줄 수 내림차순."""
        groups: Dict[str, List[str]] = defaultdict(list)
        for tag in self.legacy_tags:
            groups[self.stem(tag)].append(tag)
        out = []
        for stem, tags in groups.items():
            n = sum(self.legacy_tags[t] for t in tags)
            out.append((stem, sorted(tags, key=lambda t: -self.legacy_tags[t]), n))
        out.sort(key=lambda x: -x[2])
        return out


def build_config(land: LogLandscape, package: Optional[str] = None) -> dict:
    """지형에서 config.json 초안을 만든다."""
    tabs = []
    used_stems = set()

    # 1) 이미 이관된 도메인 → 도메인 탭 (가장 신뢰할 수 있는 신호)
    for domain, _n in land.domains.most_common():
        stem = domain.split("_")[0]
        used_stems.add(stem)
        tabs.append({"id": domain.lower(), "label": domain, "domains": [domain]})

    # 2) 레거시 군집 → legacyTagPattern 탭 (이관 전에도 화면이 정리된다)
    for stem, tags, n in land.clusters():
        if len(tabs) >= MAX_TABS:
            break
        if n < MIN_LINES_FOR_TAB or stem in used_stems:
            continue
        used_stems.add(stem)
        tabs.append({
            "id": stem.lower(),
            "label": stem.capitalize(),
            # 이관되면 여기로 들어올 도메인. 지금은 비어 있고, 라이브러리를 심는 순간 채워진다.
            "domains": [stem],
            "legacyTagPattern": "^(?:" + "|".join(re.escape(t) for t in tags) + ")$",
        })

    cfg = {
        "$schema": "./config.schema.json",
        "prefix": land.prefix,
        "bufferSize": 20000,
        "tabs": tabs,
        "issueRules": _DEFAULT_RULES,
        "funnels": [],
        "outcome": {
            "success": ["_OK", "_SUCCESS", "_DONE"],
            "failure": ["_FAIL", "_ERROR", "_TIMEOUT", "_DENIED"],
            "reasonFields": ["reason", "err", "code"],
        },
    }
    if package:
        cfg["package"] = package
    return cfg


def report(land: LogLandscape) -> str:
    """사람이 읽는 요약. 자동 생성 결과를 그대로 믿지 말라고 알려주는 게 목적이다."""
    lines = [
        f"표본 {land.total}줄  ·  구조화 {land.structured}줄 "
        f"({land.structured / land.total * 100:.1f}%)" if land.total else "표본 없음",
    ]
    if land.domains:
        lines.append("\n이미 이관된 도메인:")
        for d, n in land.domains.most_common():
            top = ", ".join(e for e, _ in land.events[d].most_common(4))
            lines.append(f"  {n:6d}  {d}   ({top})")
    else:
        lines.append("\n구조화 로그가 없습니다 — 아직 라이브러리를 심지 않은 프로젝트입니다.")
        lines.append("탭은 레거시 태그 이름으로 잡아 뒀습니다. call site 를 옮길 때마다")
        lines.append("같은 탭이 구조화 레코드로 채워집니다.")

    cl = land.clusters()
    if cl:
        lines.append("\n레거시 태그 군집 (앱이 찍은 것만):")
        for stem, tags, n in cl[:MAX_TABS]:
            shown = ", ".join(tags[:4]) + (" …" if len(tags) > 4 else "")
            lines.append(f"  {n:6d}  {stem:<14} {shown}")
    if land.other_tags:
        lines.append(f"\n제외한 시스템/타앱 태그: {len(land.other_tags)}종 "
                     f"({sum(land.other_tags.values())}줄)")
    return "\n".join(lines)


def sample(source, parser, land: LogLandscape,
           max_lines: int = 5000, max_seconds: float = 20.0) -> LogLandscape:
    """소스에서 표본을 읽어 지형을 채운다. 줄 수 또는 시간 중 먼저 오는 쪽에서 멈춘다."""
    import time
    deadline = time.monotonic() + max_seconds
    n = 0
    for line in source.lines():
        land.observe(parser.parse(line))
        n += 1
        if n >= max_lines or time.monotonic() > deadline:
            break
    source.stop()
    return land


_DEFAULT_RULES = [
    {"id": "crash", "label": "크래시", "severity": "fatal",
     "when": {"tag": "^AndroidRuntime$", "raw": "[\\w.$]+(?:Exception|Error)\\b"},
     "group": {"regex": "([\\w.$]+(?:Exception|Error))\\b", "fallback": "UnknownCrash"}},
    {"id": "anr", "label": "ANR", "severity": "fatal",
     "when": {"raw": "\\bANR in\\b"},
     "group": {"regex": "ANR in ([^\\s(]+)", "fallback": "ANR"}},
    {"id": "native", "label": "네이티브 크래시", "severity": "fatal",
     "when": {"tag": "^(DEBUG|libc)$", "raw": "signal \\d+|Fatal signal"},
     "group": {"regex": "(signal \\d+[^,]*)", "fallback": "native"}},
    {"id": "structured_error", "label": "구조화 에러", "severity": "error",
     "when": {"kind": "^structured$", "level": "^E$"},
     "group": {"template": "{domain}/{event}"}},
]
