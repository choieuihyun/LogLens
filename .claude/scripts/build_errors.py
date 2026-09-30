#!/usr/bin/env python3
# 빌드 에러 위치 추출기 (결정적, LLM 미개입)
# 역할: 빌드 출력에서 에러가 난 파일과 줄을 뽑고, 같은 에러인지 가를 해시를 만든다.
#
# 왜 builder 가 눈으로 읽지 않고 여기서 뽑나:
#   1. 에러 형식이 스택마다 다르다. javac 는 파일:줄, tsc 는 파일(줄,열), python 은 File "파일", line 줄.
#      builder 에게 한 형식만 알려 두면 나머지 스택에서는 위치를 못 뽑아 신뢰도가 LOW 로 떨어지고,
#      explorer 재실행을 돌다가 Human Gate 로 간다. 형식 목록은 여기와 어댑터의 error_patterns 에 둔다.
#   2. error_hash 는 "같은 에러가 3번 반복되면 멈춘다" 의 근거다. LLM 이 해시를 지으면 같은 에러도
#      매번 다른 값이 나와 반복 감지가 안 걸린다. 입력이 같으면 출력이 같아야 한다.
#
# 사용법: <빌드 출력> | build_errors.py [project_dir]
# 출력(json): {"locations": [{"file","line"}], "error_files": [...], "confidence": "HIGH"|null,
#              "error_hash": "..."|null, "first_error": "..."}
# confidence 는 위치를 확정했을 때만 HIGH 다. 못 뽑았을 때 MEDIUM 인지 LOW 인지는 builder 가 판단한다.

import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_config

# 여러 스택의 흔한 형식. 어댑터의 error_patterns 가 있으면 그것을 먼저 쓴다.
# 모든 패턴은 file 과 line 이름 그룹을 가져야 한다.
DEFAULT_PATTERNS = [
    r"(?:file://)?(?P<file>[\w./\\-]+\.\w+):(?P<line>\d+)",          # javac, kotlinc, gcc, go, rustc, eslint
    r"(?P<file>[\w./\\-]+\.\w+)\((?P<line>\d+),\d+\)",               # tsc
    r"File \"(?P<file>[^\"]+)\", line (?P<line>\d+)",                 # python
]
ERROR_LINE = re.compile(r"(error|Error|ERROR|failed|FAILED|e: )")


def patterns(cfg):
    ad = harness_config.adapter(cfg) or {}
    extra = [p for p in (ad.get("error_patterns") or []) if isinstance(p, str)]
    return [re.compile(p) for p in extra + DEFAULT_PATTERNS]


def inside(root, path):
    # 에러 문구 속 URL, 호스트:포트 같은 가짜 위치를 거른다. 저장소 안에 실제로 있는 파일만 위치로 본다.
    full = path if os.path.isabs(path) else os.path.join(root, path)
    full = os.path.realpath(full)
    return full.startswith(os.path.realpath(root) + os.sep) and os.path.isfile(full), full


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    cfg = harness_config.load(root)
    pats = patterns(cfg)
    text = sys.stdin.read()

    locs, seen, first_error = [], set(), None
    for line in text.splitlines():
        if first_error is None and ERROR_LINE.search(line):
            first_error = line.strip()[:300]
        for p in pats:
            for m in p.finditer(line):
                ok, full = inside(root, m.group("file"))
                if not ok:
                    continue
                rel = os.path.relpath(full, os.path.realpath(root))
                key = (rel, int(m.group("line")))
                if key not in seen:
                    seen.add(key)
                    locs.append({"file": rel, "line": key[1]})

    files = sorted({l["file"] for l in locs})
    # 해시는 줄번호를 뺀 에러 문구와 앞쪽 파일로 만든다.
    # 줄번호를 넣으면 한 줄만 밀려도 다른 에러가 되어 반복 감지가 안 걸린다.
    basis = re.sub(r"\d+", "#", first_error or "") + "|" + ",".join(files[:3])
    out = {
        "locations": locs[:50],
        "error_files": files,
        "confidence": "HIGH" if locs else None,
        "error_hash": hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12] if (first_error or files) else None,
        "first_error": first_error,
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
