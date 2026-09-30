#!/usr/bin/env python3
# 에이전트 결과 저장기 (결정적, LLM 미개입)
# 역할: 읽기 전용 에이전트가 최종 메시지로 반환한 json 을 세션 파일로 저장한다.
#
# 왜 에이전트가 직접 쓰지 않나:
#   explorer, verifier, builder 는 소스를 못 고치게 도구에서 Write 를 뺐다.
#   그런데 결과 파일을 Write 로 저장하라고 적어 두면 지시와 권한이 모순된다.
#   Bash 로 우회해 쓰게 두면 "도구로 물리적으로 막는다" 는 원칙이 구멍 난다.
#   그래서 에이전트는 반환만 하고 저장은 오케스트레이터가 이 스크립트로 한다.
#
# 왜 필수 키를 검사하나:
#   뒤 단계가 이 필드 이름으로 분기한다. 키가 빠진 json 을 그대로 저장하면
#   조건문이 None 을 읽고 조용히 엉뚱한 분기로 간다. 저장 시점에 막는다.
#
# 사용법: save_result.py <저장경로> [필수키1,필수키2,...]  (에이전트의 최종 메시지를 표준입력으로)
# 입력: 마지막 ```json 블록을 쓴다. 블록이 없으면 입력 전체를 json 으로 읽는다.
# 종료 코드: 0 저장함 / 1 json 없음, 깨짐, 필수 키 누락 (저장하지 않는다)

import json
import os
import re
import sys


def extract(text):
    blocks = re.findall(r"```json\s*\n(.*?)```", text, re.S)
    raw = blocks[-1] if blocks else text
    return json.loads(raw)


def main():
    if len(sys.argv) < 2:
        print("ERROR: 저장 경로 인자 누락")
        return 1
    out = sys.argv[1]
    required = [k for k in (sys.argv[2] if len(sys.argv) > 2 else "").split(",") if k]

    try:
        data = extract(sys.stdin.read())
    except ValueError as e:
        print("ERROR: 반환에서 json 을 읽지 못했다: %s" % e)
        return 1
    if not isinstance(data, dict):
        print("ERROR: json 최상위가 객체가 아니다")
        return 1

    missing = [k for k in required if k not in data]
    if missing:
        print("ERROR: 필수 키 누락: %s" % ",".join(missing))
        return 1

    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out)
    print("OK: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
