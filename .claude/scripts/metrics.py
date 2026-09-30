#!/usr/bin/env python3
# 런타임 게이트 메트릭 집계기 (결정적, LLM 미개입)
# 역할: runtime_metrics.jsonl(누적 로그)을 읽어 작은 요약을 출력한다.
#       LLM 은 이 작은 출력만 본다. 원본 jsonl(수천 줄)은 컨텍스트에 들어가지 않는다.
# 성격: 순수 집계(산수). 판단은 하지 않는다.
#
# 사용법: metrics.py [jsonl_경로]
#   생략 시 .claude/state/runtime_metrics.jsonl 을 찾는다 (스크립트 위치 기준).

import os
import sys
import json
from collections import defaultdict


def load_records(path):
    records = []
    if not os.path.exists(path):
        return records
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    return records


def pct(num, den):
    return (100.0 * num / den) if den else 0.0


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        # 스크립트는 .claude/scripts/ 에 있으므로 .claude/state/ 로 거슬러 올라간다
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.normpath(os.path.join(here, "..", "state", "runtime_metrics.jsonl"))

    records = load_records(path)
    if not records:
        print("메트릭 없음: %s 가 비었거나 없음. 게이트가 아직 안 돌았거나 기록 미연결." % path)
        return

    total = len(records)
    passed = sum(1 for r in records if r.get("replay_success") is True)
    failed = sum(1 for r in records if r.get("replay_success") is False)
    skipped = sum(1 for r in records if r.get("skipped") is True)
    no_flow = sum(1 for r in records if r.get("no_flow") is True)
    # 게이트 자체가 못 돈 건수 (경로 오설정, install 실패 등). 통과율 계산에서 제외한다.
    gate_error = sum(1 for r in records if r.get("gate_error"))
    effective = passed + failed

    # 커맨드별
    cmd_stats = defaultdict(lambda: {"p": 0, "f": 0})
    for r in records:
        if r.get("replay_success") is True:
            cmd_stats[r.get("command")]["p"] += 1
        elif r.get("replay_success") is False:
            cmd_stats[r.get("command")]["f"] += 1

    # 도메인(tags)별 실패
    dom_stats = defaultdict(lambda: {"run": 0, "fail": 0})
    for r in records:
        if r.get("replay_success") in (True, False):
            d = r.get("tags") or "ALL"
            dom_stats[d]["run"] += 1
            if r.get("replay_success") is False:
                dom_stats[d]["fail"] += 1

    # triage 분류 분포
    cat_count = defaultdict(int)
    for r in records:
        c = r.get("triage_category")
        if c:
            cat_count[c] += 1

    # REAL_BUG 확정률: 같은 세션에서 REAL_BUG 분류 뒤에 통과가 나오면 확정
    # (실제 코드 버그였고 수정하니 통과 = triage 분류가 옳았음)
    by_session = defaultdict(list)
    for r in records:
        by_session[r.get("session_id")].append(r)
    real_bug_cases = 0
    real_bug_confirmed = 0
    for sid, recs in by_session.items():
        for i, r in enumerate(recs):
            if r.get("triage_category") == "REAL_BUG":
                real_bug_cases += 1
                # 이후 같은 세션 레코드 중 통과가 있으면 확정
                if any(later.get("replay_success") is True for later in recs[i + 1:]):
                    real_bug_confirmed += 1

    # ---- 출력 (작게) ----
    out = []
    out.append("런타임 게이트 메트릭 (%d개 기록)" % total)
    out.append("-" * 40)
    out.append("실행: 전체 %d | 통과 %d | 실패 %d | SKIP %d | NO_FLOW %d | 게이트오류 %d"
               % (total, passed, failed, skipped, no_flow, gate_error))
    out.append("통과율: %.0f%% (실효 실행 %d건 기준)" % (pct(passed, effective), effective))
    out.append("")
    out.append("커맨드별:")
    for cmd, s in sorted(cmd_stats.items(), key=lambda kv: -(kv[1]["p"] + kv[1]["f"])):
        run = s["p"] + s["f"]
        out.append("  %-10s 실행 %d, 통과율 %.0f%%" % (cmd or "?", run, pct(s["p"], run)))
    out.append("")
    out.append("도메인별 실패 (많은 순):")
    for d, s in sorted(dom_stats.items(), key=lambda kv: -kv[1]["fail"]):
        out.append("  %-12s 실패 %d / 실행 %d" % (d, s["fail"], s["run"]))
    out.append("")
    if failed:
        out.append("triage 분류 (실패 %d건):" % failed)
        out.append("  REAL_BUG %d | FLAKY %d | FLOW_ERROR %d | ENV_STATE %d"
                   % (cat_count["REAL_BUG"], cat_count["FLAKY"],
                      cat_count["FLOW_ERROR"], cat_count["ENV_STATE"]))
        out.append("  FLAKY 비율 %.0f%% (높으면 flow 견고성 문제)"
                   % pct(cat_count["FLAKY"], failed))
        out.append("  FLOW_ERROR 비율 %.0f%% (높으면 flow 노후화)"
                   % pct(cat_count["FLOW_ERROR"], failed))
        out.append("")
    if real_bug_cases:
        out.append("REAL_BUG 확정률: %d/%d (%.0f%%) - 분류 후 수정하니 통과한 비율"
                   % (real_bug_confirmed, real_bug_cases,
                      pct(real_bug_confirmed, real_bug_cases)))
        out.append("  (낮으면 triage 가 실제버그를 오판 중 = 게이트 신뢰도 경고)")

    print("\n".join(out))


if __name__ == "__main__":
    main()
