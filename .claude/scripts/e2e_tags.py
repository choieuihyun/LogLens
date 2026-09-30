#!/usr/bin/env python3
# E2E 시나리오 태그 판독기 (결정적, LLM 미개입)
# 역할: E2E 디렉토리의 시나리오 파일에서 태그를 읽는다.
#       (1) 전체 태그 목록 = flows 가 실제로 덮는 도메인
#       (2) 주어진 태그를 가진 파일 수 = 선택적 재생 대상이 실제로 있는지
#
# 왜 셸이 아니라 여기서 읽나:
#   태그를 어떻게 적는지는 스택마다 다르다. yaml 의 tags 목록일 수도, @태그 주석일 수도 있다.
#   그 차이는 어댑터의 tag_scan 이 정한다. 셸에 awk 정규식을 박아 두면 스택이 바뀔 때 못 쓴다.
#
# 왜 커버리지를 굳이 재나:
#   "전체 회귀(ALL)" 라는 이름은 시나리오가 전 도메인을 덮을 때만 참이다.
#   실제로는 일부 도메인에만 시나리오가 있어서, 매핑 안 된 파일을 바꾸고 ALL 로 떨어지면
#   상관없는 도메인 시나리오가 통과하고 초록불이 켜진다 (거짓 PASS).
#   여기서 실측해 보고에 남긴다. 판단(통과/실패)은 바꾸지 않는다. 판단은 오케스트레이터 몫이다.
#
# 사용법: e2e_tags.py --coverage <e2e_dir>
#        e2e_tags.py --match <e2e_dir> <tag1,tag2>
# 출력: coverage 는 콤마로 이은 태그 한 줄 (없으면 빈 줄), match 는 파일 개수 한 줄.
# 태그 규칙을 모르면 coverage 는 빈 줄이다. 빈 줄은 "덮는 도메인 없음" 이 아니라 "알 수 없음" 이고,
# 게이트가 그렇게 보고한다.

import os
import re
import sys
import fnmatch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_config


def scan_rule():
    # 태그를 어떻게 적는지는 어댑터가 정하고(tag_scan), 그 안의 키 이름만은 프로젝트가 덮어쓸 수 있다.
    # 같은 스택이라도 프로젝트마다 태그를 다른 이름으로 적는 경우가 있어서다.
    # 덮어쓰기가 없으면 어댑터 값을 그대로 쓴다.
    cfg = harness_config.load()
    ad = harness_config.adapter(cfg) or {}
    ad_e2e = ad.get("e2e") or {}
    rule = dict(ad_e2e.get("tag_scan") or {})
    key_override = ((cfg or {}).get("e2e") or {}).get("tag_key")
    if key_override and rule.get("kind") == "yaml_list":
        rule["key"] = key_override
    return rule, (ad_e2e.get("file_globs") or ["*"])


def scenario_files(root, globs):
    found = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if any(fnmatch.fnmatch(name, g) for g in globs):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def tags_in(path, rule):
    kind = rule.get("kind")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return set()

    if kind == "regex":
        pattern = rule.get("pattern")
        if not pattern:
            return set()
        return set(re.findall(pattern, text))

    if kind == "yaml_list":
        # key 아래의 - 항목들을 읽는다. 다른 키가 나오면 멈춘다.
        key = rule.get("key", "tags")
        out = set()
        collecting = False
        for line in text.splitlines():
            if not collecting:
                if re.match(r"^\s*%s\s*:" % re.escape(key), line):
                    collecting = True
                continue
            m = re.match(r"^\s*-\s*([A-Za-z_][A-Za-z0-9_-]*)\s*$", line)
            if m:
                out.add(m.group(1))
                continue
            if line.strip() == "":
                continue
            break
        return out

    return set()


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print("")
        return 0

    mode, root = args[0], args[1]
    rule, globs = scan_rule()
    if not os.path.isdir(root):
        print("0" if mode == "--match" else "")
        return 0

    files = scenario_files(root, globs)

    if mode == "--coverage":
        all_tags = set()
        for f in files:
            all_tags |= tags_in(f, rule)
        print(",".join(sorted(all_tags)))
        return 0

    if mode == "--match":
        wanted = {t.strip() for t in (args[2] if len(args) > 2 else "").split(",") if t.strip()}
        if not wanted:
            print(str(len(files)))
            return 0
        if not rule:
            # 태그 규칙을 모르면 좁힐 근거가 없다. 좁히지 못했음을 0 이 아니라 전체 개수로 알린다.
            # 0 을 주면 게이트가 NO_FLOW 로 끝나 재생을 통째로 건너뛴다.
            print(str(len(files)))
            return 0
        n = 0
        for f in files:
            if tags_in(f, rule) & wanted:
                n += 1
        print(str(n))
        return 0

    print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
