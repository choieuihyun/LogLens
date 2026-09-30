#!/usr/bin/env python3
# 런타임 게이트 결과 누적 기록기 (결정적, LLM 미개입)
# 역할: 게이트 1회가 끝나면 그 결과를 runtime_metrics.jsonl 에 한 줄 기록한다.
#       세션 디렉토리의 json 은 매 스텝 덮어쓰여 사라지므로, 추세 분석을 위해 영구 로그에 누적한다.
# 성격: 순수 기록. 판단/집계는 하지 않는다 (집계는 metrics.py).
#
# 사용법: record_metric.py <session_dir> [tags]
#   tags: 그 게이트가 재생한 도메인 태그 (orchestrator 가 domains_for.py 로 산출한 값). 없으면 빈 값.
#
# 출력 위치: <.claude/state>/runtime_metrics.jsonl  (세션 디렉토리의 상위 두 단계)
#
# 호출 시점이 둘이다 (WHY 멱등이어야 하는지):
#   1) runtime_gate.sh 의 write_runner 안 - 게이트가 끝나는 모든 경로에서 자동 호출된다. 확실히 돈다.
#      다만 이 시점에는 triage 가 아직 안 돌아 triage_category 가 비어 있다.
#   2) 커맨드 문서(/fix, /feature)의 마지막 단계 - triage 결과까지 채워 다시 호출한다.
#      이쪽은 LLM 이 그 단계까지 도달해야 돌므로 누락될 수 있다.
# 두 번 불려도 줄이 두 개가 되면 안 되고, 1) 만 돌아도 기록은 남아야 한다.
# 그래서 (session_id, step_id, runtime_attempt_count) 를 키로 잡고, 같은 키가 이미 있으면
# 새로 추가하지 않고 그 줄을 갱신한다. 값 병합은 "새 값이 비어 있지 않으면 새 값, 아니면 기존 값" 이다.
# 이 규칙이면 호출 순서가 뒤바뀌어도 triage 결과가 null 로 덮이지 않는다.

import os
import sys
import json
import datetime


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


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
                # 깨진 줄은 버리지 않고 그대로 보존한다. 기록기가 남의 로그를 지우면 안 된다.
                records.append({"_raw": line})
    return records


def record_key(rec):
    return (rec.get("session_id"), rec.get("step_id"), rec.get("attempt"))


def merge(old, new):
    # 새 값이 None/빈문자열/빈리스트면 기존 값을 유지한다. 나중 호출이 앞선 정보를 지우지 않게 한다.
    merged = dict(old)
    for k, v in new.items():
        if v is None or v == "" or v == []:
            continue
        merged[k] = v
    return merged


def main():
    if len(sys.argv) < 2:
        print("ERROR: session_dir 인자 누락. 사용법: record_metric.py <session_dir> [tags]")
        sys.exit(1)

    session_dir = sys.argv[1]
    tags = sys.argv[2] if len(sys.argv) > 2 else ""

    orch = load_json(os.path.join(session_dir, "orchestrator.json"))
    runner = load_json(os.path.join(session_dir, "runner.json"))
    triage = load_json(os.path.join(session_dir, "triage.json"))

    # orchestrator.json 이 아직 없거나 깨졌어도 기록은 남겨야 하므로 디렉토리명으로 대체한다.
    session_id = orch.get("session_id") or os.path.basename(os.path.normpath(session_dir))

    # 한 줄 레코드. metrics.py 가 나중에 세션 단위로 묶어 추세/확정률을 계산할 수 있도록 충분히 담는다.
    record = {
        "ts": datetime.datetime.now().astimezone().isoformat(),
        "session_id": session_id,
        "command": orch.get("command"),
        "step_id": orch.get("step_id"),
        # 같은 스텝에서 게이트를 여러 번 돌린 경우(플래키 재시도 등)를 구분하는 회차
        "attempt": orch.get("runtime_attempt_count"),
        "tags": tags or "ALL",
        "skipped": runner.get("skipped"),
        "no_flow": runner.get("no_flow"),
        "install_success": runner.get("install_success"),
        "gate_error": runner.get("gate_error"),
        "replay_success": runner.get("replay_success"),
        "flows_total": runner.get("flows_total"),
        "flows_passed": runner.get("flows_passed"),
        "flows_failed": runner.get("flows_failed"),
        # 재생 스코프 추세용. ALL 로 떨어진 비율과 그때 실제 커버 도메인을 나중에 집계할 수 있다.
        "full_regression": runner.get("full_regression"),
        "coverage_domains": runner.get("coverage_domains"),
        # 재생한 flow 이름/결과. 나중에 "언제 무엇을 검증했나" 를 추적하려면 개수만으로는 부족하다.
        "flows": [
            {"name": f.get("name"), "status": f.get("status")}
            for f in (runner.get("flows") or [])
        ],
        "triage_category": triage.get("category"),
        "triage_confidence": triage.get("confidence"),
    }

    # 세션 디렉토리: .claude/state/sessions/<id>  ->  .claude/state 에 누적 로그를 둔다
    state_dir = os.path.normpath(os.path.join(session_dir, "..", ".."))
    out_path = os.path.join(state_dir, "runtime_metrics.jsonl")

    records = load_records(out_path)
    key = record_key(record)

    # 같은 키의 마지막 줄을 찾아 갱신한다. 없으면 새로 추가한다.
    target = None
    for i in range(len(records) - 1, -1, -1):
        if "_raw" in records[i]:
            continue
        if record_key(records[i]) == key:
            target = i
            break

    if target is None:
        records.append(record)
        action = "append"
    else:
        records[target] = merge(records[target], record)
        action = "amend"

    # 원자적 교체. 기록 중 중단돼도 기존 로그가 반토막 나지 않게 한다.
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        for rec in records:
            if "_raw" in rec:
                f.write(rec["_raw"] + "\n")
            else:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    os.replace(tmp_path, out_path)

    final = records[target] if target is not None else record
    print("metric %s: %s (session=%s step=%s replay_success=%s triage=%s)" % (
        action, out_path, final.get("session_id"), final.get("step_id"),
        final.get("replay_success"), final.get("triage_category")))


if __name__ == "__main__":
    main()
