#!/usr/bin/env python3
# 하네스 업데이트 알림 (결정적, LLM 미개입)
# 역할: 이 프로젝트에 설치된 하네스가 하네스 저장소보다 뒤처졌는지 확인해 한 줄로 알린다.
#
# 왜 필요한가:
#   하네스는 계속 고쳐지는데, 설치된 프로젝트는 재설치하지 않으면 옛 버전으로 돈다.
#   사용자가 하네스 저장소를 들여다보지 않는 한 업데이트가 있는지 알 길이 없다.
#   /fix, /feature, /setup 이 시작할 때 이것을 불러 알린다.
#
# 무엇과 비교하나 (설치 기록 .claude/.harness-manifest 첫머리):
#   1. 로컬 하네스 클론의 HEAD 가 설치한 커밋보다 앞서 있다 -> install.sh 재실행
#   2. 원격(origin)의 HEAD 가 로컬 클론보다 앞서 있다     -> git pull 후 install.sh 재실행
#
# 알리기만 한다. 작업을 막지 않는다. 확인에 실패하면(클론이 없음, 네트워크 없음, 시간 초과) 조용히 넘어간다.
# 원격 확인은 네트워크를 쓰므로 하루에 한 번만 한다 (.claude/state/version-check.json). --now 로 바로 확인한다.
#
# 사용법: harness_version.py [--now] [project_dir]
# 출력: 알릴 것이 있으면 한두 줄, 없으면 아무것도 출력하지 않는다. 종료 코드는 항상 0.

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_manifest

DAY = 24 * 3600


def git(path, *args, timeout=5):
    try:
        r = subprocess.run(["git", "-C", path] + list(args), capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def main():
    args = [a for a in sys.argv[1:] if a != "--now"]
    now = "--now" in sys.argv
    root = args[0] if args else os.getcwd()
    dest = os.path.join(root, ".claude")
    m = harness_manifest.meta(dest)
    installed, path = m.get("harness_commit", ""), m.get("harness_path", "")
    if not installed:
        print("하네스 설치 기록에 버전이 없다 (예전 설치본). 하네스 저장소에서 install.sh 를 한 번 다시 돌리면 이후로 업데이트를 알린다.")
        return 0
    if not path or not os.path.isdir(os.path.join(path, ".git")):
        return 0

    msgs = []
    head = git(path, "rev-parse", "HEAD")
    if head and head != installed:
        n = git(path, "rev-list", "--count", "%s..%s" % (installed, head))
        if n and n != "0":
            msgs.append("하네스 업데이트 %s건이 아직 이 프로젝트에 반영되지 않았다. 반영: bash %s/install.sh %s" % (n, path, root))

    state_dir = os.path.join(dest, "state")
    state = os.path.join(state_dir, "version-check.json")
    last = 0
    try:
        last = json.load(open(state)).get("remote_checked_at", 0)
    except (OSError, ValueError):
        pass
    if now or time.time() - last > DAY:
        remote = git(path, "ls-remote", "origin", "HEAD", timeout=5).split("\t")[0]
        # 원격 커밋이 로컬에 이미 들어 있으면(로컬이 앞서 있거나 같으면) 알리지 않는다.
        # 로컬에 없는 커밋이면 merge-base 가 실패하는데, 그것도 "새 버전" 이다.
        contained = subprocess.run(["git", "-C", path, "merge-base", "--is-ancestor", remote, head],
                                   capture_output=True).returncode == 0 if remote and head else True
        if remote and head and remote != head and not contained:
            msgs.append("원격 하네스에 새 버전이 있다. 반영: cd %s && git pull && bash install.sh %s" % (path, root))
        try:
            os.makedirs(state_dir, exist_ok=True)
            json.dump({"remote_checked_at": time.time()}, open(state, "w"))
        except OSError:
            pass

    for msg in msgs:
        print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
