#!/usr/bin/env python3
# 에이전트 도구 추가 반영기 (결정적, LLM 미개입)
# 역할: project.json 의 agent_tools 에 적힌 추가 도구를 설치된 에이전트의 tools 줄에 더한다.
#
# 왜 에이전트 파일을 직접 고치지 않고 설정에 적나:
#   외부 지식 도구(문서 서버, 사내 위키, 노트 앱)는 프로젝트마다 다르다. 그래서 세팅 때 붙인다.
#   그런데 .claude/agents 는 하네스 원본의 사본이라, 직접 고치면 재설치 때 "대상에서 고친 파일" 로 걸리고
#   덮으면 연결이 사라진다. 설정에 적어 두면 재설치 뒤 이 스크립트가 다시 반영한다.
#
# 무엇을 더했는지는 tools_extra 줄에 남긴다. 다음 반영 때 그것을 먼저 빼고 다시 더하므로 몇 번 돌려도 같다.
# 설치기는 두 줄(tools, tools_extra)을 비교에서 뺀다.
#
# 사용법: apply_agent_tools.py [project_dir]
# 종료 코드: 0 반영함(또는 할 것 없음) / 1 설정에 적힌 에이전트가 없음

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_config


def split(v):
    return [t.strip() for t in v.split(",") if t.strip()]


def apply(path, extra):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return False
    lines = m.group(1).split("\n")
    tools_i = next((i for i, l in enumerate(lines) if l.startswith("tools:")), None)
    if tools_i is None:
        return False
    old_extra = []
    for l in lines:
        if l.startswith("tools_extra:"):
            old_extra = split(l[len("tools_extra:"):])
    base = [t for t in split(lines[tools_i][len("tools:"):]) if t not in old_extra]
    lines = [l for l in lines if not l.startswith("tools_extra:")]
    tools_i = next(i for i, l in enumerate(lines) if l.startswith("tools:"))
    added = [t for t in extra if t not in base]
    lines[tools_i] = "tools: " + ", ".join(base + added)
    if added:
        lines.insert(tools_i + 1, "tools_extra: " + ", ".join(added))
    new = "---\n" + "\n".join(lines) + "\n---\n" + text[m.end():]
    if new != text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)
    return True


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    cfg = harness_config.load(root) or {}
    wanted = cfg.get("agent_tools") or {}
    agents_dir = os.path.join(os.path.dirname(cfg.get("_path", os.path.join(root, ".claude", "x"))), "agents")
    if not os.path.isdir(agents_dir):
        print("에이전트 폴더가 없다: %s" % agents_dir)
        return 1
    missing = []
    for name in sorted(os.listdir(agents_dir)):
        path = os.path.join(agents_dir, name, "AGENT.md")
        if os.path.isfile(path):
            apply(path, [t for t in (wanted.get(name) or []) if isinstance(t, str)])
    for name in wanted:
        if not os.path.isfile(os.path.join(agents_dir, name, "AGENT.md")):
            missing.append(name)
    if missing:
        print("설정에 있지만 설치되지 않은 에이전트: %s" % ", ".join(missing))
        return 1
    print("반영: %s" % (", ".join("%s(+%d)" % (k, len(v)) for k, v in wanted.items()) or "추가 도구 없음"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
