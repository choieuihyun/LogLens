#!/usr/bin/env python3
# 설치 기록 (결정적, LLM 미개입)
# 역할: 설치할 때 복사한 파일의 해시를 남기고, 재설치할 때 "대상에서 고친 파일" 만 가려낸다.
#
# 왜 필요한가:
#   예전에는 대상 파일을 지금의 하네스 원본과 비교했다. 그러면 하네스가 갱신된 파일도
#   "대상에서 고친 파일" 로 잡혀, 하네스를 한 번이라도 고치면 업그레이드할 때마다 설치가 멈췄다.
#   고쳤는지는 "그때 설치한 것" 과 비교해야 안다. 그 기준을 여기 남긴다.
#
# 에이전트의 tools 줄은 비교에서 뺀다. /setup 이 붙인 MCP(agent_tools)가 반영되는 자리다.
#
# 기록 첫머리에는 어느 하네스에서 설치했는지를 남긴다 (# 로 시작하는 줄):
#   # harness_commit <커밋>   # harness_path <하네스 클론 경로>   # harness_remote <원격 주소>   # installed_at <시각>
# harness_version.py 가 이것으로 업데이트가 있는지 알린다.
#
# 사용법:
#   harness_manifest.py write   <.claude 경로> <하위 폴더...>      설치 직후 기록
#   harness_manifest.py meta    <.claude 경로> <키>                기록 첫머리 값 하나 출력 (없으면 빈 줄)
#   harness_manifest.py changed <.claude 경로> <하네스 루트> <원본:하위 ...>
#       대상에서 고친 파일을 한 줄에 하나 출력한다. 기록이 없으면 첫 줄에 "#NO_MANIFEST" 를 내고
#       원본과 비교한다 (하네스가 갱신한 파일도 섞여 나온다).

import hashlib
import os
import re
import sys

NAME = ".harness-manifest"
TOOLS = re.compile(r"^tools(_extra)?:.*\n?", re.M)


def digest(path):
    with open(path, "rb") as f:
        data = f.read()
    if path.endswith("AGENT.md"):
        data = TOOLS.sub("", data.decode("utf-8", "replace")).encode("utf-8")
    return hashlib.sha1(data).hexdigest()


def walk(root):
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for f in files:
            yield os.path.join(d, f)


def meta(dest):
    out = {}
    mpath = os.path.join(dest, NAME)
    if os.path.isfile(mpath):
        for line in open(mpath, encoding="utf-8"):
            if line.startswith("# "):
                k, _, v = line[2:].rstrip("\n").partition(" ")
                out[k] = v
    return out


def write(dest, subs):
    lines = ["# %s %s" % (k, os.environ.get("HM_" + k.upper(), "")) for k in
             ("harness_commit", "harness_path", "harness_remote", "installed_at")]
    for sub in subs:
        base = os.path.join(dest, sub)
        if not os.path.isdir(base):
            continue
        for p in sorted(walk(base)):
            lines.append("%s  %s" % (digest(p), os.path.relpath(p, dest)))
    with open(os.path.join(dest, NAME), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def changed(dest, harness, pairs):
    manifest = {}
    mpath = os.path.join(dest, NAME)
    if os.path.isfile(mpath):
        for line in open(mpath, encoding="utf-8"):
            if line.startswith("#"):
                continue
            h, _, rel = line.rstrip("\n").partition("  ")
            if rel:
                manifest[rel] = h
    else:
        print("#NO_MANIFEST")
    for pair in pairs:
        src_sub, _, sub = pair.partition(":")
        base = os.path.join(dest, sub)
        if not os.path.isdir(base):
            continue
        for p in sorted(walk(base)):
            rel = os.path.relpath(p, dest)
            if manifest:
                if rel not in manifest:
                    print("%s (설치 기록에 없는 파일)" % rel)
                elif digest(p) != manifest[rel]:
                    print(rel)
            else:
                src = os.path.join(harness, src_sub, os.path.relpath(p, base))
                if not os.path.isfile(src):
                    print("%s (하네스에 없는 파일)" % rel)
                elif digest(p) != digest(src):
                    print(rel)


def main():
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "write":
        write(a[1], a[2:])
        return 0
    if len(a) == 3 and a[0] == "meta":
        print(meta(a[1]).get(a[2], ""))
        return 0
    if len(a) >= 3 and a[0] == "changed":
        changed(a[1], a[2], a[3:])
        return 0
    print("사용법: harness_manifest.py write|changed ...")
    return 3


if __name__ == "__main__":
    sys.exit(main())
