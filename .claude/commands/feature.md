# /feature - 신규 기능 개발 파이프라인

신규 기능을 기획 토론부터 구현/검증/문서화까지 자동으로 진행한다.
fix 와 같은 하네스(세션 격리 + orchestrator.json + Human Gate + 런타임 게이트) 위에,
앞단에 기획 3단계(DISCUSS -> SPEC -> PLAN-CHECK)와 필수 승인 게이트를 더한 파이프라인이다.

순차 실행:
DISCUSS -> SPEC -> PLAN -> PLAN-CHECK -> [필수 승인] -> EXPLORE -> IMPLEMENT -> (VERIFY + BUILD) -> 런타임 게이트 -> DOCUMENT

이 커맨드의 핵심 차별점은 두 가지다:
1. 프로젝트 도메인을 아는 기획 토론 (상태 동기화, 공유 상태 전파, 외부 시스템 등 예외를 능동 제기)
2. SPEC 주도 런타임 게이트. 신규 기능은 보존할 과거 동작이 없으므로 E2E 시나리오를 구현이 아니라 구현 전 동결된 수용조건에서 만든다 (자기충족 함정 회피)

---

## 세션 초기화 (필수)

매 호출마다 고유 세션 디렉토리를 생성하여 동시 실행 격리를 보장한다.

```bash
SESSION_ID="feature-$(date +%Y%m%d-%H%M%S)-$(openssl rand -hex 2)"
SESSION_DIR=".claude/state/sessions/${SESSION_ID}"
mkdir -p "${SESSION_DIR}"
echo "[/feature] SESSION_ID=${SESSION_ID}"
echo "[/feature] SESSION_DIR=${SESSION_DIR}"
```

이 출력을 그대로 사용자에게 보여준다.
이후 본 문서의 `${SESSION_DIR}` 는 위에서 생성된 절대 경로다.
모든 상태 파일은 `${SESSION_DIR}` 하위에만 작성한다.

---

## 시작 전 준비

### 하네스 업데이트 확인 (알리기만 한다)

```bash
python3 .claude/scripts/harness_version.py
```

출력이 있으면 사용자에게 첫머리에 그 줄을 그대로 한 번 알리고 **계속 진행한다.** 업데이트 때문에 멈추거나 대신 재설치하지 않는다.
재설치는 사용자가 정한다. 출력이 없으면 아무 말도 하지 않는다.


`${SESSION_DIR}/orchestrator.json` 을 아래 초기값으로 생성한다.

```json
{
  "version": 2,
  "session_id": "<SESSION_ID>",
  "session_dir": "<SESSION_DIR>",
  "command": "feature",
  "step_id": 1,
  "updated_at": "<현재 시각 ISO 8601>",
  "status": "INIT",
  "feature_request": "<$ARGUMENTS 또는 대화 맥락의 기능 요청>",
  "attempt_count": 0,
  "allowed_to_modify": [],
  "allowed_to_create": [],
  "forbidden_rules": [
    {"type": "glob", "value": "<project.json 의 forbidden_globs 를 그대로 옮긴다>"}
  ],
  "shared_event_gate": true,
  "risk_flags": [],
  "risk_level": "LOW",
  "human_gate_required": false,
  "approval_status": "PENDING",
  "approved_scope": null,
  "spec_attempt": 0,
  "plan_check_attempt": 0,
  "last_error_hash": null,
  "same_error_count": 0,
  "last_explorer_step": 0,
  "termination_reason": null,
  "runtime_attempt_count": 0,
  "flaky_retry_count": 0,
  "flow_fix_count": 0,
  "last_triage_category": null
}
```

`${SESSION_DIR}/implementer.json`: `{"recent_patches": []}`
`${SESSION_DIR}/verifier.json`: `{"verification_passed": null, "findings": [], "summary": {"total": 0, "high": 0, "medium": 0, "low": 0}}`
`${SESSION_DIR}/builder.json`: `{"build_success": null, "error_hash": null, "error_files": [], "error_confidence": null}`
`${SESSION_DIR}/runner.json`: `{"skipped": null, "no_flow": null, "install_success": null, "replay_success": null, "failed_flow": null, "screenshot_path": null, "gate_error": null}`
`${SESSION_DIR}/triage.json`: `{"category": null, "confidence": null, "next_action": null, "suspected_files": []}`

forbidden_rules 주의: fix 와 달리 project.json 의 `risk_globs`(공유 상태 전파 경로 등)를 하드 금지하지 않는다.
신규 기능은 새 신호(이벤트, 액션, 메시지)를 추가할 수 있기 때문이다. 대신 shared_event_gate 로 다뤄 Human Gate 를 건다 (아래 5단계).
`forbidden_globs`(의존성/빌드 설정)는 그대로 하드 금지다.

---

## 에이전트 결과 저장

explorer, builder, verifier, triage 는 결과 파일을 직접 쓰지 않는다. 소스를 못 고치게 도구에서 쓰기 권한을 뺐기 때문이다.
대신 최종 메시지 끝에 json 블록 하나로 결과를 반환한다. 저장은 오케스트레이터가 한다.

에이전트가 끝나면 최종 메시지 원문을 그대로 넘긴다:

```bash
python3 .claude/scripts/save_result.py "${SESSION_DIR}/<파일>" <필수 키> <<'AGENT_RESULT'
<에이전트 최종 메시지 원문>
AGENT_RESULT
```

| 에이전트 | 파일 | 필수 키 |
|---|---|---|
| explorer | `explorer-proposal.json` | `step_id,proposed_allowed_to_modify,risk_flags,risk_level` |
| builder | `builder.json` | `step_id,build_success,error_hash,error_files,error_confidence` |
| verifier | `verifier.json` | `step_id,verification_passed,findings,summary` |
| triage | `triage.json` | `step_id,category,confidence,next_action,suspected_files` |

exit 1 (json 없음, 깨짐, 필수 키 누락) 이면 저장하지 않는다. 같은 에이전트를 한 번 재호출하며
"결과를 최종 메시지 끝의 json 블록으로 반환하라" 고 다시 요구한다. 두 번째도 실패하면 Human Gate 다.
json 을 손으로 고쳐 저장하지 않는다. 뒤 단계가 이 필드로 분기하므로 추측한 값은 엉뚱한 분기를 만든다.

## 0단계: 기획 토론 (DISCUSS)

orchestrator.json status 를 "DISCUSS" 로 업데이트한다.

**discuss 에이전트를 호출한다.**
호출 프롬프트 상단에 반드시 다음을 명시한다:

```
session_dir: <SESSION_DIR>
```

전달 정보: feature_request (기능 요청 내용).

에이전트는 적응형 다단계 토론(최대 5라운드)으로 예외/엣지/추가가능성을 발굴하고
`${SESSION_DIR}/discuss.json` 을 저장한다.

완료 후 discuss.json 을 읽는다.

**중계 루프.** 서브에이전트가 사용자에게 직접 못 묻는 환경이면 discuss 는 `status: "WAITING_USER"` 와
`pending_questions` 를 남기고 끝난다. 그때는:
1. `pending_questions` 를 사용자에게 그대로 묻는다 (선택지가 있으면 AskUserQuestion, 한 번에 하나씩)
2. 답을 discuss.json 의 `rounds` 에 `{round, qa: [{id, question, answer}]}` 로 붙이고 `pending_questions` 를 비운다
3. discuss 를 다시 부른다 (같은 session_dir). `status` 가 `DONE` 이 될 때까지 반복한다. `round` 가 5 를 넘으면 멈추고 Human Gate
답을 오케스트레이터가 대신 정하지 않는다. 사용자가 "모름" 이면 그 말을 그대로 적는다 (discuss 가 open_questions 로 넘긴다).

### Orchestrator 판단

- `status` 가 `WAITING_USER` 면 위 중계 루프로 간다
- discuss.json 이 없거나 `status` 가 `DONE` 인데 in_scope 가 비어 있으면 discuss 재호출
- domain_flags.sync 또는 shared_event_new 가 true 면 risk_level 을 최소 MEDIUM 으로 설정
- domain_flags 를 orchestrator.json risk_flags 에 반영 (SYNC / EVENT / THREAD / DB 등)

---

## 1단계: 명세 동결 (SPEC)

orchestrator.json status 를 "SPEC" 으로 업데이트한다. spec_attempt 를 1 증가시킨다.

**종료 조건: spec_attempt > 3 → Human Gate** (수용조건이 계속 확정 안 됨).

**spec 에이전트를 호출한다** (프롬프트 상단에 session_dir 명시).

에이전트는 discuss.json 을 E2E 변환 가능한 수용조건으로 동결해 `${SESSION_DIR}/spec.json` 을 저장한다.

완료 후 spec.json 을 읽는다.

### Orchestrator 판단

- acceptance_criteria 가 비어있으면 spec 재호출
- open_questions 가 남아있으면 AskUserQuestion 으로 사용자에게 확인 후 spec 재호출
- runtime_observable=true 인 수용조건이 하나도 없으면 (시나리오로 관찰할 수 없는 기능) 그 사실을 기록한다.
  이 경우 뒤 런타임 게이트는 NO_FLOW 통과가 되며 보고에 명시된다

---

## 2단계: 설계 (PLAN)

orchestrator.json status 를 "PLAN" 으로 업데이트한다.

**planner 에이전트를 호출한다** (프롬프트 상단에 session_dir 명시).

에이전트는 spec.json 을 프로젝트 관례에 맞는 파일/이벤트 계획과 UI 식별자 매핑으로 설계해
`${SESSION_DIR}/plan.json` 을 저장한다.

완료 후 plan.json 을 읽는다.

### Orchestrator 판단

- allowed_to_create 를 orchestrator.json 에 반영
- plan.events 중 requires_human_gate=true 가 있으면 human_gate_required 후보로 표시 (승인 게이트에서 함께 처리)
- plan.risks 를 risk_flags 에 병합

---

## 3단계: 계획 검증 (PLAN-CHECK)

orchestrator.json status 를 "PLAN_CHECK" 로 업데이트한다. plan_check_attempt 를 1 증가시킨다.

**종료 조건: plan_check_attempt > 3 → Human Gate** (planner<->checker 무한 루프 방지).

**plan-checker 에이전트를 호출한다** (프롬프트 상단에 session_dir 명시).

에이전트는 plan 이 spec 수용조건을 목표역산으로 달성하는지 검증해 `${SESSION_DIR}/plan-check.json` 을 저장한다.

완료 후 plan-check.json 을 읽는다.

### Orchestrator 판단

| verdict | 동작 |
|---|---|
| FAIL | planner 재호출 (findings 전달), 2단계로 복귀. plan_check_attempt 유지 누적 |
| PASS_WITH_NOTES | 4단계(승인)로. MEDIUM notes 를 승인 요약에 포함 |
| PASS | 4단계(승인)로 |

---

## 4단계: 승인 게이트 (APPROVAL) - 필수

orchestrator.json status 를 "APPROVAL" 로 업데이트한다.
신규 기능은 항상 여기서 멈추고 사용자 승인을 받아야 구현을 시작한다.

사용자에게 계획 요약을 제시한다:
- feature_title 과 goal (spec.json)
- 수용조건 목록 (acceptance_criteria, UI 관찰가능/수동검증 구분)
- 설계 요약 (plan.design_summary)
- 신규 생성 파일(allowed_to_create)과 수정 후보(modify_hint)
- 새 공유 신호 여부, sync 설계 여부
- plan-check 의 PASS_WITH_NOTES 주의사항
- risk_flags 와 risk_level
- 수정 후보 중 `risk_globs`, `risk_axes` 에 걸리는 공유 파일 (이 승인이 그 파일 수정까지 포함한다는 것을 분명히 말한다)

AskUserQuestion 으로 승인 여부를 묻는다 (승인 / 수정요청 / 중단).

- 승인 → approval_status "APPROVED", 5단계로.
  무엇을 보고 승인했는지 orchestrator.json 의 `approved_scope` 에 남긴다:
  `{"files": allowed_to_create + modify_hint, "risk_flags": [...], "shared_files": [위 공유 파일]}`.
  5단계는 이 범위를 벗어날 때만 다시 멈춘다
- 수정요청 → 요청 내용에 따라 해당 단계(DISCUSS/SPEC/PLAN)로 복귀
- 중단 → status "ABORTED_BY_USER" 로 종료 보고

승인 없이는 5단계 이후로 진행하지 않는다.

---

## 5단계: 탐색 (EXPLORE)

orchestrator.json status 를 "EXPLORING" 으로 업데이트한다.
승인된 계획을 실제 코드에 배선하기 위해 수정해야 할 기존 파일을 확정하는 단계다.

**explorer 에이전트를 호출한다** (프롬프트 상단에 session_dir 명시).
전달 정보: plan.json 의 modify_hint 와 reuse_patterns (신규 파일은 planner 가 이미 정함. explorer 는 수정할 기존 파일만 확정).

완료 후 반환을 「에이전트 결과 저장」대로 `${SESSION_DIR}/explorer-proposal.json` 에 저장하고 읽는다.

### Orchestrator 판단

1. proposed_allowed_to_modify 에 forbidden_rules(forbidden_globs) 필터 적용. 걸리면 human_gate_required true (승인과 무관하게 항상)
2. `approved_scope` 와 대조한다. 사용자는 4단계에서 이미 위험을 보고 승인했다. 같은 위험으로 두 번 묻지 않는다.
   아래 중 하나라도 해당하면 Human Gate, 아니면 멈추지 않는다:
   - 수정 대상에 `approved_scope.files` 밖의 파일이 있다
   - risk_flags 에 `approved_scope.risk_flags` 에 없던 축이 있다
   - `risk_globs` 나 `risk_axes` 에 걸리는 공유 파일 중 `approved_scope.shared_files` 에 없던 것이 있다 (shared_event_gate)
   explorer 가 같은 요인으로 등급만 올린 것(MEDIUM -> HIGH)은 새 위험이 아니다. 멈추지 않고 보고에만 적는다
3. allowed_to_modify = 필터링된 기존 파일 목록. 최종 수정 범위 = allowed_to_modify + allowed_to_create
4. status "IMPLEMENTING" 으로

---

## 6단계: 구현 (IMPLEMENTING)

orchestrator.json status 를 "IMPLEMENTING" 으로 업데이트한다. attempt_count 를 1 증가시킨다.

**종료 조건: attempt_count >= 5 → FAILED_MAX_ITER 로 종료.**

**implementer 에이전트를 호출한다** (프롬프트 상단에 session_dir 명시).
전달 정보:
- plan.json (설계, steps, test_id_map)
- spec.json (수용조건)
- 최종 수정 범위: allowed_to_modify + allowed_to_create

**코드 출력 금지 규칙 (필수):**
- 변경 코드를 응답 텍스트에 출력하지 않는다
- 모든 코드 변경은 Write/Edit 로 파일에 직접 반영한다
- 대용량 파일은 500줄 이하 단위로 나눠 여러 번 작성한다

**신규 파일 생성 주의:** implementer 는 allowed_to_create 에 없는 파일은 새로 만들지 않는다.
신규 화면이면 plan 이 정한 화면 구조를 따르고, test_id_map 의 UI 식별자를 인터랙티브 요소에 부여한다.
색상/테마 규칙은 project.json 의 `docs.conventions` 문서를 따른다.

**feature-mode 지시 (필수, sync 충돌 해소):** implementer 의 실패 반환 조건에는
"risk_level HIGH 이고 Sync 로직 변경이 필요하면 Human Gate" 가 있다. 이 규칙은 버그픽스에서
기존 sync 로직을 함부로 건드리지 말라는 의미다. 그러나 신규 기능은 sync 흐름을 새로 추가하는 것이 정상이며,
이미 4단계 승인 게이트에서 사람이 risk 를 검토하고 승인했다. 따라서 프롬프트에 다음을 명시한다:
"feature-mode. 이 작업은 승인 게이트를 통과한 신규 기능 추가다. plan.sync_design 에 따른 신규 sync 흐름 추가는
허용되며 Human Gate 로 바운스하지 않는다. 단 기존 sync 로직의 의미를 바꾸는 변경은 여전히 보고한다."
이 지시가 없으면 멀티디바이스 sync 신규 기능(도메인 프로브 1순위)이 구현 단계에서 막힌다.

완료 후 `${SESSION_DIR}/implementer.json` 을 읽고 fix 와 동일하게 무의미 diff 를 검증한다:
- changed_lines == 0 → FAILED_MEANINGLESS_DIFF
- 동일 패치(diff_hash + target_files_sorted) 반복 → FAILED_MEANINGLESS_DIFF

---

## 7단계: 검증 + 빌드 (VERIFYING + BUILDING)

orchestrator.json status 를 "VERIFYING" 으로 업데이트한다.

**verifier 와 builder 를 병렬로 호출한다** (각 프롬프트 상단에 session_dir 명시).

verifier 에게 전달: 대상 파일(allowed_to_create + allowed_to_modify), spec.json 과 plan.json 이 세션에 있다는 것.
검증 항목(완료 기준, UI 식별자, 공유 상태 전파, 연결 누락)은 verifier 문서가 정한다.

builder 에게 추가 전달 정보 없음 (session_dir 만으로 충분).

두 에이전트 완료까지 기다린 뒤 각 반환을 「에이전트 결과 저장」대로 verifier.json 과 builder.json 에 저장하고 읽어 판단한다:

| verifier | builder | 판단 |
|---|---|---|
| PASS | 성공 | 7.5단계로 |
| PASS | 실패 | implementer 재호출 (빌드 에러 수정) |
| FAIL | 성공 | implementer 재호출 (검증 실패 항목 수정) |
| FAIL | 실패 | implementer 재호출 (양쪽 결과 전달) |

빌드 실패 시 fix 와 동일하게 same_error_count 를 관리한다 (같은 에러 3회 → FAILED_SAME_ERROR).
implementer 재호출 시 6단계로 돌아가며 attempt_count 종료조건이 동일 적용된다.

---

## 7.5단계: 런타임 게이트 (RUNTIME) - SPEC 주도

verifier PASS + builder 성공 후 실행한다. 구현이 수용조건을 실제로 만족하는지 실기기로 검증한다.
이 단계가 이 커맨드의 핵심 신규 설계다. E2E 시나리오를 구현이 아니라 spec 에서 만든다.

orchestrator.json status 를 "RUNTIME" 으로 업데이트한다.

### 시나리오 생성 (spec 주도, 자기충족 함정 회피)

시나리오 내용은 구현을 관찰해서 쓰지 않는다. 구현 전 동결된 spec.json + plan.json 에서 만든다.
검증(assert)의 근거는 spec 에서, 진입(navigation)의 셀렉터는 기존 화면에서 온다.

먼저 재생 스코프 태그를 산출한다. 이 태그는 시나리오 파일에 심을 태그와 반드시 동일해야 한다.

```bash
TAGS=$(python3 .claude/scripts/domains_for.py <allowed_to_create + allowed_to_modify 의 소스 파일 경로들>)
```

시나리오 작성 규칙 (파일 형식과 문법은 project.json 의 `docs.e2e_guide` 와 기존 시나리오를 본뜬다):
1. spec.json 의 runtime_observable=true 이고 verify_manual=false 인 수용조건만 대상으로 한다
2. 대상이 하나도 없으면(시나리오로 관찰할 수 없는 기능) 시나리오를 만들지 않고 NO_FLOW 로 처리한다 (아래 판단 참조)
3. 파일에 태그를 심는다. 태그는 위 TAGS 값이다.
   TAGS 가 "ALL"(도메인 규칙이 모르는 새 폴더이거나 공유 영역이라 특정 못함)이면
   plan.json 의 primary_domain 으로 태그한다.
   전체 회귀(ALL)에서는 어차피 이 시나리오도 포함되며, 태그를 달아두면 이후 표적 재생에서도 잡힌다.
   태그가 TAGS 와 어긋나면 태그 매칭에서 빠져 NO_FLOW 로 오인 통과하므로 절대 어긋나면 안 된다.
4. 진입 프리앰블: spec.json 각 수용조건 e2e.entry 의 스텝을 그대로 쓴다.
   entry 의 `진입`, `준비`, `조작` 스텝을 시나리오 도구의 문법으로 옮긴다 (인증 전제는 `docs.e2e_guide` 참조).
   UI 가 있으면 기존 화면의 텍스트 셀렉터 네비게이션으로 given 상태까지 도달한다.
   entry 가 없으면 첫 조작에서 죽으므로, spec 에 entry 가 비어있으면 spec 을 재호출해 채운다
5. 본문: UI 면 e2e.act_element / assert_element 를 plan.json 의 test_id_map 값으로 식별자 셀렉터로 바꾼다.
   UI 가 없으면 surface 와 element 를 요청이나 명령으로 바꾼다. assert_text 는 그 값 그대로 검증한다
6. `<e2e.dir>/<주 도메인>/<feature_title 슬러그>` 로 저장한다 (하위 폴더까지 재귀 수집된다)

생성 시나리오의 뼈대 (실제 문법은 스택마다 다르다):

```
태그: <TAGS 또는 primary_domain>
---
진입                              (entry 의 진입, 준비)
given 상태까지 이동               (entry 의 조작)
대상 조작                         (act_element. UI 면 test_id_map 의 식별자)
결과 확인                         (assert_element)
값 검증                           (assert_text)
```

### 게이트 실행

runtime_gate.sh 인자는 <session_dir> [project_dir] [tags] 다.
runtime_gate.sh 의 2번째 인자는 시나리오 경로가 아니라 프로젝트 경로다. 빈 문자열을 넘기면
스크립트가 자기 위치(.claude/scripts)에서 워크트리 루트를 산출한다. 워크트리마다 .claude 가
따로 복사되므로 이 방식이 항상 옳다. 시나리오 선택은 3번째 인자 태그로만 이뤄진다.

```bash
bash .claude/scripts/runtime_gate.sh "${SESSION_DIR}" "" "$TAGS"
```

게이트는 시나리오 전체에서 TAGS 에 해당하는 것만 재생한다. 방금 생성한 시나리오가 TAGS 로 태그돼 있으므로 함께 재생된다.
완료 후 `${SESSION_DIR}/runner.json` 을 읽는다.

### Orchestrator 판단

| runner.json | 판단 |
|---|---|
| gate_error != null | 게이트 자체가 못 돎 (경로 오설정/install 실패). 통과 아님. 즉시 Human Gate |
| skipped=true | SKIP. 사용자 보고 후 8단계로 (기기 미연결) |
| no_flow=true (관찰 가능 수용조건 없음) | 시나리오로 볼 수 없는 기능. 보고 후 8단계로 (수동 검증 항목은 verify_manual 로 남음) |
| no_flow=true (관찰 가능 수용조건 있음) | 오인 통과. 통과로 처리하지 않는다. 태그 불일치 버그이므로 7.5 시나리오 생성으로 복귀 |
| replay_success=true | 8단계로 (수용조건 동작 검증됨) |
| replay_success=false | triage 호출 (아래) |

핵심 구분: feature 의 no_flow 는
"검증할 관찰 가능 수용조건이 애초에 없음" 일 때만 통과다.
반드시 spec.json 에 runtime_observable=true 수용조건이 있는지 먼저 확인한다.
관찰 가능 수용조건이 있는데도 no_flow=true 라면 시나리오 태그가 TAGS 와 어긋나 매칭 0이 된 것이다 (오인 통과).
이 경우 통과시키지 말고 7.5 시나리오 생성으로 돌아가 태그를 TAGS 와 일치시킨다.
이것이 이 게이트가 조용히 초록불만 켜는 것을 막는 핵심 방어다.

### replay 실패 시 triage 호출

runtime_attempt_count 를 1 증가시킨다.
**triage 에이전트를 호출한다** (프롬프트 상단에 session_dir 명시).
완료 후 반환을 「에이전트 결과 저장」대로 triage.json 에 저장하고 읽어 category 에 따라 분기한다:

| category | next_action | 동작 | 종료 조건 |
|---|---|---|---|
| REAL_BUG | REINVOKE_IMPLEMENTER | 6단계 재호출, suspected_files 전달, attempt_count++ | 같은 화면 3연속 실패 → Human Gate |
| FLAKY | RETRY_REPLAY | flaky_retry_count++ 후 게이트 재시도 | 2회 초과 → Human Gate |
| FLOW_ERROR | FIX_FLOW | flow_fix_count++ 후 시나리오 수정 → 재시도 | 2회 초과 → Human Gate |
| ENV_STATE | HUMAN_GATE | 미로그인/권한/기기 상태. 사람 개입 | 즉시 |

last_triage_category 를 기록한다. confidence 가 LOW 이면 next_action 을 HUMAN_GATE 로 올린다.

### 메트릭 기록

기본 기록은 runtime_gate.sh 가 자동으로 한다. 게이트가 끝나는 모든 경로(통과 / 실패 / SKIP /
NO_FLOW / gate_error)에서 record_metric.py 가 호출되므로, 이 단계까지 못 와도 게이트 결과는 남는다.

여기서는 triage 결과를 채워 넣기 위해 한 번 더 호출한다. record_metric.py 는 멱등이라
(session_id, step_id, attempt) 가 같으면 줄을 추가하지 않고 기존 줄을 갱신한다.
triage 를 돌리지 않았다면 이 단계는 생략해도 된다. 추세는 metrics.py 로 언제든 집계한다.

```bash
python3 .claude/scripts/record_metric.py "${SESSION_DIR}" "$TAGS"
```

---

## 8단계: 문서화 (DOCUMENTING)

런타임 게이트 처리 후 실행한다. 신규 기능은 문서화 트리거(클래스 추가)에 항상 해당한다.

orchestrator.json status 를 "DOCUMENTING" 으로 업데이트한다.

**documenter 에이전트를 호출한다** (프롬프트 상단에 session_dir 명시).
전달 정보:
- 변경/생성 파일 목록 (`changed_files`)
- 도메인 (`domains`: 게이트에 넘긴 TAGS 와 같은 값)
- 신규 기능 요약 (spec.json goal)
- 문서 모드: 해당 도메인 DOMAIN.md 가 있으면 update, 없으면 `.claude/templates/DOMAIN.md.tmpl` 로 신규 생성(create)

### 시나리오 셀렉터 강화 (선택)

런타임 게이트를 통과한 시나리오는 이미 UI 식별자 셀렉터로 만들어졌으므로 별도 강화가 불필요하다.
단 생성 시 텍스트 셀렉터로 폴백한 부분이 있으면 plan 의 test_id_map 값으로 교체한다.
skipped/no_flow 였으면 이 단계를 건너뛴다.

---

## Human Gate 절차

human_gate_required 가 true 가 된 상황:

1. orchestrator.json status 를 "HUMAN_GATE" 로 업데이트한다
2. 사용자에게 보고한다: SESSION_ID/SESSION_DIR, 발동 사유, 현재 단계, allowed_to_modify + allowed_to_create,
   risk_flags/risk_level, 지금까지 진행 요약
3. 사용자 지시를 기다린다

---

## 종료 처리

### 성공 (SUCCESS)
- SESSION_ID 보고
- 생성/수정된 파일 목록
- 빌드 성공 확인
- 런타임 게이트 결과 (통과 / SKIP / NO_FLOW 중 무엇인지 명시)
- 수동 검증 항목(verify_manual=true 수용조건, 예: 두 기기 간 동기화) 목록을 사용자에게 남긴다
- documenter 결과 (DOMAIN.md 생성/갱신, 노트 앱 동기화 여부)

### 실패 (FAILED_*)
orchestrator.json termination_reason 을 업데이트하고 보고한다:

```
SESSION_ID: <SESSION_ID>
종료 이유: [FAILED_MAX_ITER / FAILED_SAME_ERROR / FAILED_MEANINGLESS_DIFF / ABORTED_BY_USER]
현재 단계: <status>
시도 횟수: N회
마지막 상태: [요약]
권장 행동: [수동 확인 필요 사항]
```
