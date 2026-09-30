#!/usr/bin/env python3
# 완료 기준(DoD) 기계 검증기 (결정적, LLM 미개입)
# 역할: project.json 의 dod_checks 규칙을 바뀐 파일에 적용해 위반을 출력한다.
# 성격: 정규식 대조만 한다. 판단은 하지 않는다. 판정은 verifier 몫이다.
#
# 왜 스크립트로 빼나:
#   "화면 완료 기준" 중 기계로 확정 가능한 항목은 LLM 이 눈으로 보면 놓친다.
#   grep 으로 확정되는 것은 grep 이 해야 매번 같은 결과가 나온다.
#   무엇을 요구하고 무엇을 금지하는지는 프로젝트 컨벤션이므로 코드가 아니라 설정에 둔다.
#
# 규칙 형식 (project.json 의 dod_checks):
#   {"id": "DOD_MISSING_PREVIEW", "applies_to": "*Screen.kt", "require": "@Preview",
#    "message": "미리보기 함수 누락"}
#   {"id": "DOD_HARDCODED_COLOR", "applies_to": "*Screen.kt", "forbid": "Color\\(0x",
#    "message": "하드코딩 색상"}
#   require 는 없으면 위반, forbid 는 있으면 위반이다.
#
# 사용법: dod_check.py <파일1> <파일2> ...
# 출력: 위반 한 줄씩 "<id>: <파일>[:<줄번호>] <메시지>". 위반이 없으면 아무것도 출력하지 않는다.
# 종료코드: 0 위반 없음 / 1 위반 있음 / 2 규칙 없음(검증 자체를 못 함)
#
# 규칙이 없을 때 0(통과)을 주지 않는다. 검사하지 않은 것과 통과한 것은 다르다.

import os
import re
import sys
import fnmatch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_config


def main():
    files = sys.argv[1:]
    cfg = harness_config.load()
    rules = (cfg or {}).get("dod_checks") or []

    if not rules:
        print("DOD_NO_RULES: project.json 에 dod_checks 가 없어 기계 검증을 못 했다")
        return 2
    if not files:
        return 0

    violations = 0
    for path in files:
        name = os.path.basename(path)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        text = "\n".join(lines)

        for rule in rules:
            glob = rule.get("applies_to") or "*"
            if not (fnmatch.fnmatch(name, glob) or fnmatch.fnmatch(path, glob)):
                continue
            rid = rule.get("id", "DOD")
            msg = rule.get("message", "")

            need = rule.get("require")
            if need and not re.search(need, text):
                print("%s: %s %s" % (rid, path, msg))
                violations += 1

            ban = rule.get("forbid")
            if ban:
                for i, line in enumerate(lines, 1):
                    if re.search(ban, line):
                        print("%s: %s:%d %s" % (rid, path, i, msg))
                        violations += 1

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
