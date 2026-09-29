"""구현 목록(catalog)을 앱 소스에서 뽑는다.

손으로 적은 목록은 앱에 항목이 추가되는 순간 낡는다. 그래서 뷰어가 뜰 때마다 앱 소스를
훑어 "앱이 처리하는 key" 를 다시 모은다. 무엇을 key 로 볼지는 설정의 정규식이 정한다.
이 파일은 어느 앱의 규칙도 모른다 — 훑는 방법만 안다.

한 key 가 여러 곳에서 참조되면 설명 주석이 달린 곳을 대표 위치(where)로 삼는다.
설명은 같은 줄의 `// ...` 주석에서 읽는다. 주석 처리된 코드는 설명이 아니므로 버린다.
"""

from __future__ import annotations

import fnmatch
import os
import re
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

# 훑지 않을 디렉토리. 빌드 산출물에는 소스 사본(stub)이 들어 있어 위치가 엉뚱하게 잡힌다.
_SKIP_DIRS = {"build", ".git", ".gradle", ".idea", "node_modules", "out", "bin", ".cxx"}
_DEFAULT_INCLUDE = ["*.java", "*.kt"]
# 주석이 설명이 아니라 주석 처리된 코드인지. 틀려도 이름이 빠질 뿐이라 느슨하게 잡는다.
_CODE_LIKE = re.compile(r"[;{}]|\w\(|\s=\s|^\s*(if|else|return|for|while|new|val|var)\b")
_NAME_MAX = 30


def extract(source: Dict[str, object]) -> Tuple[List[dict], Optional[str]]:
    """(항목 목록, 오류) 를 돌려준다. 오류가 있어도 예외를 던지지 않는다.

    소스 루트가 없는 경우(다른 PC, 경로 오타)에 뷰어가 안 뜨면 안 된다.
    """
    root = os.path.abspath(os.path.expanduser(str(source.get("root") or "")))
    if not source.get("root") or not os.path.isdir(root):
        return [], f"소스 루트를 찾지 못했다: {root}"
    try:
        pattern = re.compile(str(source.get("pattern") or ""))
    except re.error as e:
        return [], f"pattern 정규식 오류: {e}"
    if not pattern.pattern:
        return [], "pattern 이 비어 있다"
    include = list(source.get("include") or _DEFAULT_INCLUDE)

    found: "OrderedDict[str, dict]" = OrderedDict()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for fn in sorted(filenames):
            if not any(fnmatch.fnmatch(fn, g) for g in include):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            if not pattern.search(text):
                continue
            rel = os.path.relpath(path, root)
            for no, line in enumerate(text.splitlines(), 1):
                for m in pattern.finditer(line):
                    key = m.group(1) if m.groups() else m.group(0)
                    _add(found, key, rel, no, line[m.end():])
    return list(found.values()), None


def _add(found: dict, key: str, rel: str, no: int, rest: str) -> None:
    e = found.get(key)
    if e is None:
        e = found[key] = {"code": key, "name": None, "note": None,
                          "where": f"{rel}:{no}", "refs": 0}
    e["refs"] += 1
    desc = _trailing_comment(rest)
    if desc and not e["name"]:
        # 설명이 달린 곳이 그 key 를 처리하는 곳일 가능성이 높다. 위치도 그리로 옮긴다.
        e["where"] = f"{rel}:{no}"
        if len(desc) > _NAME_MAX:
            e["name"] = desc[:_NAME_MAX].rstrip() + "…"
            e["note"] = desc
        else:
            e["name"] = desc


def _trailing_comment(rest: str) -> Optional[str]:
    i = rest.find("//")
    if i < 0:
        return None
    c = re.sub(r"\s+", " ", rest[i + 2:]).strip().rstrip("*/").strip()
    if not c or _CODE_LIKE.search(c):
        return None
    return c
