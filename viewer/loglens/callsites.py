"""로그 한 줄 → 그 로그를 만든 코드 줄.

이벤트 이름(evt=LOGIN_START)은 소스에서 로그를 찍는 호출에 문자열로 들어 있다.
그래서 이름으로 "찍는 줄" 은 바로 찾는다. 문제는 앱이 로그를 도우미 메서드로 감싸는 경우다.

    SignInFlow.java:192   AuthTrace.loginStart(flowId, …)          ← 보고 싶은 곳 (호출부)
    AuthTrace.java:39      LogLens.i(AUTH, "LOGIN_START", …)       ← 이름으로 찾은 곳 (도우미)

찍는 줄이 속한 메서드를 누가 부르는지 한 단계 따라가서 호출부를 후보로 낸다.
  - 부르는 곳이 없으면 찍는 줄 자체가 업무 코드다 → 찍는 줄이 답
  - 부르는 곳이 여럿이면 전부 후보 (한 곳으로 단정하지 않는다)
  - 너무 많으면(흔한 이름) 추정이 무의미하다 → 찍는 줄로 물러난다

소스를 읽어 추정하는 것이라 틀릴 수 있다. 그래서 후보마다 근거(via)를 같이 준다.
이 파일은 어느 앱의 규칙도 모른다 — 찍는 호출의 모양은 설정의 정규식이 정한다.
"""

from __future__ import annotations

import fnmatch
import os
import re
from typing import Dict, List, Optional, Tuple

from .catalog import _SKIP_DIRS

# LogLens 호출에서 이벤트 이름. 캡처그룹 1 이 이벤트 이름이다.
DEFAULT_PATTERN = r'LogLens\.(?:[vdiwe]|payload)\(\s*[^,()]+,\s*"([A-Z0-9_]+)"'
_DEFAULT_INCLUDE = ["*.java", "*.kt"]
# 부르는 곳이 이보다 많으면 도우미가 아니라 흔한 이름으로 본다
MAX_CALLERS = 8

# 메서드 선언. 자바는 "반환형 이름(", 코틀린은 "fun 이름(". 제어문은 선언이 아니다.
_JAVA_DECL = re.compile(
    r"^\s*(?:@\w+\s+)*(?:(?:public|private|protected|static|final|synchronized|abstract|native)\s+)*"
    r"[\w<>\[\],.? ]+?\s+(\w+)\s*\([^;]*$")
_KT_DECL = re.compile(r"\bfun\s+(?:<[^>]+>\s*)?(?:[\w.]+\.)?(\w+)\s*\(")
_COMMENT_LINE = re.compile(r"^\s*(//|/\*|\*)")
_NOT_DECL = {"if", "for", "while", "switch", "catch", "return", "new", "else", "synchronized",
             "throw", "try", "do", "when"}


def _files(root: str, include: List[str]):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for fn in sorted(filenames):
            if any(fnmatch.fnmatch(fn, g) for g in include):
                path = os.path.join(dirpath, fn)
                try:
                    with open(path, encoding="utf-8", errors="replace") as f:
                        yield os.path.relpath(path, root), f.read().splitlines()
                except OSError:
                    continue


def _enclosing_method(lines: List[str], idx: int) -> Optional[str]:
    """idx 줄이 속한 메서드 이름. 위로 올라가며 가장 가까운 선언을 찾는다."""
    for i in range(idx, max(-1, idx - 200), -1):
        ln = lines[i]
        m = _KT_DECL.search(ln) or _JAVA_DECL.match(ln)
        if m and m.group(1) not in _NOT_DECL:
            return m.group(1)
    return None


def find(source: Dict[str, object], event: str) -> Tuple[dict, Optional[str]]:
    """({"emits": [...], "targets": [...]}, 오류). 예외를 던지지 않는다."""
    out = {"event": event, "emits": [], "targets": []}
    root = os.path.abspath(os.path.expanduser(str(source.get("root") or "")))
    if not source.get("root") or not os.path.isdir(root):
        return out, f"소스 루트를 찾지 못했다: {root}"
    try:
        pattern = re.compile(str(source.get("pattern") or DEFAULT_PATTERN))
    except re.error as e:
        return out, f"pattern 정규식 오류: {e}"
    include = list(source.get("include") or _DEFAULT_INCLUDE)

    files = list(_files(root, include))
    # 1) 이 이벤트를 찍는 줄. 주석 속 사용 예시(javadoc 등)는 호출이 아니다.
    for rel, lines in files:
        for i, ln in enumerate(lines):
            if _COMMENT_LINE.match(ln):
                continue
            for m in pattern.finditer(ln):
                if (m.group(1) if m.groups() else m.group(0)) == event:
                    out["emits"].append({"where": f"{rel}:{i + 1}",
                                         "method": _enclosing_method(lines, i),
                                         "file": rel})
    # 2) 찍는 줄이 든 메서드를 부르는 곳
    seen = set()
    for e in out["emits"]:
        callers = _callers(files, e["file"], e["method"]) if e["method"] else []
        if not callers or len(callers) > MAX_CALLERS:
            why = ("부르는 곳이 너무 많아 추정하지 않음" if callers else "이 줄이 곧 업무 코드")
            _push(out["targets"], seen, e["where"], f"로그를 찍는 줄 ({why})")
            continue
        cls = os.path.splitext(os.path.basename(e["file"]))[0]
        for where in callers:
            _push(out["targets"], seen, where, f"{cls}.{e['method']}() 를 부르는 곳")
    for e in out["emits"]:
        e.pop("file", None)
    return out, None


def _callers(files, decl_file: str, method: str) -> List[str]:
    """method 를 부르는 줄. 다른 파일은 클래스명.method( 로, 같은 파일은 method( 로 찾는다."""
    cls = os.path.splitext(os.path.basename(decl_file))[0]
    qualified = re.compile(r"\b" + re.escape(cls) + r"\s*\.\s*" + re.escape(method) + r"\s*\(")
    bare = re.compile(r"(?<![\w.])" + re.escape(method) + r"\s*\(")
    found = []
    for rel, lines in files:
        same = rel == decl_file
        for i, ln in enumerate(lines):
            if _COMMENT_LINE.match(ln):
                continue
            if same:
                if bare.search(ln) and not (_KT_DECL.search(ln) or _JAVA_DECL.match(ln)):
                    found.append(f"{rel}:{i + 1}")
            elif qualified.search(ln):
                found.append(f"{rel}:{i + 1}")
    return found


def _push(targets: list, seen: set, where: str, via: str) -> None:
    if where not in seen:
        seen.add(where)
        targets.append({"where": where, "via": via})


# ── 크래시 스택 줄 → 소스 파일 ───────────────────────────────────────────────
# at com.x.ChatRepo$send$1.invokeSuspend(ChatRepo.kt:88)
# 파일은 클래스명이 아니라 괄호 안의 파일명과 패키지 경로로 찾는다. 코틀린 최상위 함수는 FooKt,
# 내부/람다 클래스는 Foo$Bar 라서 클래스명으로는 파일을 못 맞힌다.

FRAME_FILE = re.compile(r"^[\w$-]+\.(java|kt)$")
FRAME_PKG = re.compile(r"^[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)*$|^$")


def find_frame(source: Dict[str, object], pkg: str, file: str) -> Tuple[List[str], Optional[str]]:
    """(소스 상대경로 후보, 오류). 소스 세트가 여럿이면 후보가 여럿일 수 있다."""
    if not FRAME_FILE.match(file or "") or not FRAME_PKG.match(pkg or ""):
        return [], "스택 줄 모양이 아니다"
    root = os.path.abspath(os.path.expanduser(str(source.get("root") or "")))
    if not source.get("root") or not os.path.isdir(root):
        return [], f"소스 루트를 찾지 못했다: {root}"
    want = os.path.join(*pkg.split("."), file) if pkg else file
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        if file in filenames:
            rel = os.path.relpath(os.path.join(dirpath, file), root)
            if rel == want or rel.endswith(os.sep + want):
                found.append(rel)
    return sorted(found), None
