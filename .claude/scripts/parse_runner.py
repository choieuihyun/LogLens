#!/usr/bin/env python3
# runner.json 작성기
# 역할: runtime_gate.sh 가 넘긴 사실들(배포/재생 결과)과 E2E JUnit 리포트를 합쳐 runner.json 을 기록한다.
# 성격: 결정적. JUnit XML 파싱과 실패 스크린샷 탐색만 한다. 판단은 하지 않는다 (판단은 triage).

import os
import glob
import json
import datetime
import xml.etree.ElementTree as ET


def env_value(name):
    # 셸이 넘긴 "true"/"false"/"null"/숫자 문자열을 파이썬 값으로 변환
    raw = os.environ.get(name, "null")
    if raw == "true":
        return True
    if raw == "false":
        return False
    if raw == "null" or raw == "":
        return None
    if raw.lstrip("-").isdigit():
        return int(raw)
    return raw


def read_step_id(session_dir):
    # orchestrator.json 에서 현재 step_id 를 읽는다. 없으면 0.
    path = os.path.join(session_dir, "orchestrator.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("step_id", 0)
    except Exception:
        return 0


def parse_junit(report_path):
    # E2E JUnit 리포트에서 전체/통과/실패 개수와 첫 실패 시나리오, 실패 메시지를 추출한다.
    # JUnit XML 은 스택이 달라도 형식이 같다. 그래서 이 파서는 어댑터에 묶이지 않는다.
    # flows 목록도 함께 남긴다. 개수만 있으면 나중에 "그때 무엇을 검증했나" 를 알 수 없다.
    result = {
        "flows_total": 0,
        "flows_passed": 0,
        "flows_failed": 0,
        "failed_flow": None,
        "failed_step": None,
        "flows": [],
    }
    if not report_path or not os.path.exists(report_path):
        return result
    try:
        tree = ET.parse(report_path)
        root = tree.getroot()
    except Exception:
        return result

    # testcase 는 testsuite 깊이에 상관없이 전부 수집
    for tc in root.iter("testcase"):
        result["flows_total"] += 1
        name = tc.get("name") or tc.get("id") or "unknown"
        failure = tc.find("failure")
        error = tc.find("error")
        bad = failure if failure is not None else error

        # flow 에 붙은 도메인 태그 (선택적 재생 스코프 추적용)
        tags = None
        for prop in tc.iter("property"):
            if prop.get("name") == "tags":
                tags = prop.get("value")
                break

        entry = {
            "name": name,
            "file": tc.get("file"),
            "tags": tags,
            "duration_sec": tc.get("time"),
            "status": "FAILED" if bad is not None else "PASSED",
            "failed_step": None,
        }

        if bad is not None:
            result["flows_failed"] += 1
            msg = (bad.get("message") or bad.text or "").strip()
            entry["failed_step"] = msg.splitlines()[0][:200] if msg else None
            if result["failed_flow"] is None:
                result["failed_flow"] = name
                result["failed_step"] = entry["failed_step"]
        else:
            result["flows_passed"] += 1

        result["flows"].append(entry)

    # 이름 순으로 고정한다. 재생 순서는 실행마다 달라서 그대로 두면 diff 가 지저분해진다.
    result["flows"].sort(key=lambda f: f["name"])
    return result


def find_screenshot(debug_dir):
    # 디버그 산출물에서 가장 최근 png 를 실패 스크린샷으로 본다 (flatten 출력이라 평탄 구조)
    if not debug_dir or not os.path.isdir(debug_dir):
        return None
    pngs = glob.glob(os.path.join(debug_dir, "**", "*.png"), recursive=True)
    if not pngs:
        return None
    pngs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return pngs[0]


def main():
    session_dir = os.environ.get("RG_SESSION", ".")
    report_path = os.environ.get("RG_REPORT", "")
    debug_dir = os.environ.get("RG_DEBUG", "")

    install_success = env_value("RG_INSTALL")
    replay_success = env_value("RG_REPLAY")
    skipped = env_value("RG_SKIPPED")
    skip_reason = env_value("RG_SKIPREASON")
    no_flow = env_value("RG_NOFLOW")
    e2e_exit = env_value("RG_EEXIT")
    # 게이트 자체가 못 돈 사유 (경로 오설정, install 실패 등). 정상 수행이면 None.
    gate_error = env_value("RG_GATEERR")

    # 재생 스코프와 실제 커버리지.
    # WHY: replay_success=true 만으로는 "무엇을 검증했나" 를 알 수 없다. 특히 전체 회귀(ALL)는
    #      시나리오가 덮는 도메인만 도는데, 이름 때문에 전 도메인을 검증한 것으로 오인되기 쉽다.
    #      바꾼 파일의 도메인이 coverage_domains 에 없으면 그 통과는 해당 화면을 검증하지 않은 것이다.
    requested_tags = os.environ.get("RG_TAGS", "") or None
    coverage_raw = os.environ.get("RG_COVERAGE", "") or ""
    coverage_domains = [d for d in coverage_raw.split(",") if d]
    full_regression = env_value("RG_FULLREG") is True

    junit = parse_junit(report_path)
    screenshot = find_screenshot(debug_dir) if replay_success is False else None

    # 리포트 파일이 실제로 있었는지. 재생이 실패했는데 리포트가 없으면 러너가 리포트를 쓰기 전에 죽은 것이다.
    # triage 가 "시나리오가 실패했다" 와 "러너 자체가 못 돌았다" 를 가를 근거로 쓴다.
    report_found = bool(report_path) and os.path.exists(report_path)

    # 방어: 게이트가 정상적으로 돌았는데 testcase 가 0개면 실제 검증된 flow 가 없는 것이다.
    # (태그 매칭 0 등) 통과로 오인하지 않도록 no_flow 로 처리한다.
    # 단 게이트 자체가 실패한 경우(gate_error) 나 install 이 깨진 경우는 여기 해당하지 않는다.
    # 그때까지 no_flow 로 덮으면 "커버리지 없음(=통과)" 으로 오인돼 실패가 조용히 묻힌다.
    # 재생이 실패한 경우(replay_success=false)도 마찬가지다. 러너가 리포트를 쓰기 전에 죽으면
    # testcase 가 0개로 읽히는데, 이걸 no_flow 로 덮으면 시나리오로 볼 수 없는 버그의 경로에서 SUCCESS 가 된다.
    if (
        not skipped
        and gate_error is None
        and install_success is not False
        and replay_success is not False
        and junit["flows_total"] == 0
    ):
        no_flow = True
        replay_success = None

    runner = {
        "step_id": read_step_id(session_dir),
        "updated_at": datetime.datetime.now().astimezone().isoformat(),
        "skipped": bool(skipped),
        "skip_reason": skip_reason,
        "no_flow": bool(no_flow),
        "install_success": install_success,
        "replay_success": replay_success,
        "flows_total": junit["flows_total"],
        "flows_passed": junit["flows_passed"],
        "flows_failed": junit["flows_failed"],
        "failed_flow": junit["failed_flow"],
        "failed_step": junit["failed_step"],
        # 키 이름은 스택 중립이다. 이 키는 record_metric.py 와 metrics.py 도 읽으므로
        # 바꿀 때 세 파일을 같이 바꿔야 한다. 이름이 갈리면 집계가 조용히 0 이 된다.
        "e2e_exit_code": e2e_exit,
        "report_found": report_found,
        "screenshot_path": screenshot,
        "gate_error": gate_error,
        # 재생 스코프. full_regression=true 면 ALL 경로로 돈 것이다.
        "requested_tags": requested_tags,
        "full_regression": full_regression,
        # flows 가 실제로 덮는 도메인. ALL 이어도 이 목록 밖은 검증되지 않았다.
        "coverage_domains": coverage_domains,
        # 이번 게이트가 실제로 재생한 flow 목록. 개수만으로는 무엇을 검증했는지 남지 않는다.
        "flows": junit["flows"],
    }

    out_path = os.path.join(session_dir, "runner.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(runner, f, ensure_ascii=False, indent=2)

    print("runner.json 기록 완료: " + out_path)
    print("  skipped=%s no_flow=%s install=%s replay=%s gate_error=%s (%s/%s flow 통과)" % (
        runner["skipped"], runner["no_flow"], runner["install_success"],
        runner["replay_success"], runner["gate_error"],
        runner["flows_passed"], runner["flows_total"]))
    if runner["full_regression"]:
        print("  전체 회귀(ALL). 실제 커버 도메인: %s" % (
            ", ".join(runner["coverage_domains"]) or "없음"))
        print("  주의: 바꾼 파일의 도메인이 위에 없으면 이 통과는 그 화면을 검증하지 않았다.")
    for f in runner["flows"]:
        print("    [%s] %-24s %ss  (%s)" % (
            f["status"], f["name"], f["duration_sec"] or "?", f["file"] or "?"))


if __name__ == "__main__":
    main()
