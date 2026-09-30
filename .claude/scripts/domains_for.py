#!/usr/bin/env python3
# 파일 경로 -> 도메인 태그 매핑기 (결정적)
# 역할: 바뀐 파일 목록(allowed_to_modify)을 받아 런타임 게이트가 돌릴 도메인 태그를 산출한다.
# 안전 원칙: 매핑이 불확실하거나 공유 코드면 ALL(전체 회귀)을 반환한다.
#           scope 를 좁혀 회귀를 놓치는 것보다 느려도 전체를 도는 편이 안전하다.
#           설정 파일이 없거나 깨져 있어도 마찬가지로 ALL 이다. 여기서 죽으면 게이트가 못 돈다.
#
# 사용법: domains_for.py <path1> <path2> ...
#        domains_for.py --self-check   (설정의 도메인 목록이 실제 폴더와 맞는지 대조)
# 출력: 도메인 태그를 콤마로 연결한 한 줄. 전체 회귀면 "ALL".
#
# 매핑 규칙은 코드가 아니라 project.json 의 domains 에 있다. 규칙 종류는 둘뿐이다.
#
#   dir_rules   경로의 어떤 디렉토리 이름이 곧 도메인이다.
#               {"under": "src/features", "shared": ["common"], "known": ["chat", "search"]}
#               under 바로 다음 세그먼트를 도메인으로 본다.
#               shared 에 있으면 공유 코드이므로 ALL. known 이 비어 있지 않은데 거기 없으면 ALL.
#
#   prefix_rules  폴더로 안 나뉜 평평한 파일은 파일명 접두사가 도메인을 가리킨다.
#               {"under": "src/pages", "map": {"OrderList": "order", "OrderDetail": "order", "Cart": "cart"}}
#               긴 접두사를 먼저 맞춘다. 짧은 접두사가 긴 것을 가로채면 엉뚱한 도메인이 나온다.
#
# 확실한 것만 넣는다. 애매하면 넣지 않고 ALL 로 두는 편이 낫다.
# 잘못 매핑하면 엉뚱한 도메인 flow 만 돌고 통과해서, 커버리지 없음보다 나쁘다.

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_config


def rules_of(cfg):
    # 설정에서 규칙 두 종류를 꺼낸다. 없으면 빈 목록 (즉 전부 ALL).
    #
    # under 가 비어 있는 항목은 규칙이 아니라 **안 채운 빈칸**이다. 템플릿의 예시 뼈대가 그대로 남은 것이다.
    # 이걸 규칙으로 받으면 빈 문자열이 "경로 전체" 로 해석돼 첫 디렉토리 이름을 도메인으로 잡는다.
    # 그러면 설정을 안 했는데도 엉뚱한 태그로 좁혀 재생하고, 커버리지 없는 통과가 만들어진다.
    # 안 채운 빈칸은 모르는 것이므로 없는 것으로 친다 (-> ALL).
    domains = (cfg or {}).get("domains") or {}
    dir_rules = [r for r in (domains.get("dir_rules") or []) if (r.get("under") or "").strip()]
    prefix_rules = [r for r in (domains.get("prefix_rules") or [])
                    if (r.get("under") or "").strip() and (r.get("map") or {})]
    return dir_rules, prefix_rules


def normalized(path):
    return path.replace("\\", "/")


def after_marker(norm, under):
    # under 이후의 상대 경로를 돌려준다. under 가 경로에 없으면 None.
    # 절대경로로 넘어오든 저장소 상대경로로 넘어오든 같게 동작하도록 부분 일치로 찾는다.
    under = under.strip("/")
    if not under:
        return norm
    idx = norm.find(under + "/")
    if idx == -1:
        return None
    return norm[idx + len(under) + 1:]


def domain_of(path, dir_rules, prefix_rules):
    # 경로 하나를 도메인 토큰으로 변환한다. 불확실하면 None(=ALL 유발) 반환.
    norm = normalized(path)

    for rule in dir_rules:
        rel = after_marker(norm, rule.get("under", ""))
        if rel is None:
            continue
        parts = [p for p in rel.split("/") if p]
        if len(parts) < 2:
            # under 바로 밑의 평평한 파일이다. 디렉토리 규칙으로는 판단할 수 없다.
            continue
        sub = parts[0]
        if sub in (rule.get("shared") or []):
            return None                       # 공유 코드 -> 전체 회귀
        known = rule.get("known") or []
        if known and sub not in known:
            return None                       # 등록 안 된 폴더 -> 전체 회귀
        return sub

    for rule in prefix_rules:
        rel = after_marker(norm, rule.get("under", ""))
        if rel is None:
            continue
        parts = [p for p in rel.split("/") if p]
        if len(parts) != 1:
            continue                          # 하위 폴더가 있으면 접두사 규칙 대상이 아니다
        filename = parts[0]
        table = rule.get("map") or {}
        for prefix in sorted(table, key=len, reverse=True):
            if filename.startswith(prefix):
                return table[prefix]
        return None                           # 매핑 불확실 -> 전체 회귀

    return None


def self_check(cfg):
    # 설정의 known 목록이 실제 폴더와 일치하는지 대조한다.
    # 폴더를 새로 만들고 등록을 잊으면 그 도메인 변경이 조용히 ALL 로 떨어진다.
    # ALL 은 flows 전체를 돌리는데 flows 가 전 도메인을 덮지 않으면
    # "전체 회귀 통과" 가 실제로는 일부만 검증한 결과가 된다 (거짓 초록불).
    if not cfg:
        print("self-check 불가: project.json 을 찾지 못했다")
        return 1

    dir_rules, _ = rules_of(cfg)
    if not dir_rules:
        print("self-check 대상 없음: domains.dir_rules 가 비어 있다 (모든 변경이 ALL 로 간다)")
        return 1

    root = cfg.get("project_root") or os.path.dirname(os.path.dirname(cfg.get("_path", "")))
    ok = True
    for rule in dir_rules:
        under = rule.get("under", "")
        base = os.path.join(root, under)
        if not os.path.isdir(base):
            print("경로 없음: %s" % base)
            ok = False
            continue
        shared = set(rule.get("shared") or [])
        known = set(rule.get("known") or [])
        actual = {d for d in os.listdir(base)
                  if os.path.isdir(os.path.join(base, d))} - shared
        if not known:
            print("%s: known 이 비어 있다 (하위 폴더 %d개를 모두 도메인으로 인정)" % (under, len(actual)))
            continue
        missing = sorted(actual - known)       # 폴더는 있는데 미등록 -> ALL 로 샌다
        stale = sorted(known - actual)         # 등록됐는데 폴더 없음 -> 죽은 항목
        if missing:
            ok = False
            print("%s: 미등록 폴더 (변경 시 ALL 로 떨어짐, known 에 추가할 것): %s"
                  % (under, ", ".join(missing)))
        if stale:
            ok = False
            print("%s: 죽은 항목 (known 에 있으나 실제 폴더 없음): %s" % (under, ", ".join(stale)))
        if not missing and not stale:
            print("%s: known %d개가 실제 폴더와 일치" % (under, len(known)))
    return 0 if ok else 1


def main():
    cfg = harness_config.load()
    paths = sys.argv[1:]

    if paths and paths[0] == "--self-check":
        sys.exit(self_check(cfg))

    if not paths:
        print("ALL")
        return

    dir_rules, prefix_rules = rules_of(cfg)
    if not dir_rules and not prefix_rules:
        # 설정이 없거나 규칙이 비었다. 매핑을 모르는 것이므로 넓은 쪽으로 간다.
        print("ALL")
        return

    domains = set()
    for p in paths:
        d = domain_of(p, dir_rules, prefix_rules)
        if d is None:
            # 하나라도 불확실하거나 공유면 전체 회귀로 확정
            print("ALL")
            return
        domains.add(d)

    print(",".join(sorted(domains)))


if __name__ == "__main__":
    main()
