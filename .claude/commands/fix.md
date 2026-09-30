# /fix - 버그 수정 파이프라인 (통합)

주어진 버그를 자동으로 분석하고 수정한다.
순차 실행: 인테이크 → explorer → implementer → builder → 런타임 게이트(E2E 재생) 루프

이 커맨드는 세 가지 진입 경로를 하나의 본체로 처리한다. 문제를 어디서 가져오는지만 다르고
분석/수정/검증 흐름은 완전히 동일하다.

| 호출 | 인테이크 모드 | 문제 출처 |
|---|---|---|
| `/fix <버그 설명>` | `manual` | 인자 또는 대화 맥락 |
| `/fix --build` | `build` | builder 를 먼저 돌려 컴파일/lint 에러 확보 |
| `/fix --crash [issue_id]` | `crash` | 크래시 리포팅 서비스의 이슈 + 스택트레이스 |

인테이크 모드는 0단계에서만 분기한다. **1단계부터 종료까지는 모드를 참조하지 않는다.**
유일한 예외는 종료 처리의 크래시 이슈 노트 한 줄이다.
분기를 본문 중간으로 흘리면 오케스트레이터가 조건을 놓치므로, 새 모드를 추가할 때도 0단계에만 넣는다.

런타임 게이트는 기회주의적이다. 시나리오로 관찰 가능한 버그일 때만 동작하고, 그렇지 않은 버그는 NO_FLOW 로 통과한다.

관련 커맨드와의 경계:
- `/feature` 는 승인 게이트에서 멈추고 flow 를 spec 에서 만든다 (제어 흐름이 다름 → 별도 유지)

---

## 세션 초기화 (필수)

매 호출마다 고유 세션 디렉토리를 생성하여 동시 실행 격리를 보장한다.

Bash로 다음을 실행한다 (그대로 한 번 실행하면 된다):

```bash
SESSION_ID="fix-$(date +%Y%m%d-%H%M%S)-$(openssl rand -hex 2)"
SESSION_DIR=".claude/state/sessions/${SESSION_ID}"
mkdir -p "${SESSION_DIR}"
echo "[/fix] SESSION_ID=${SESSION_ID}"
echo "[/fix] SESSION_DIR=${SESSION_DIR}"
```

이 단계의 출력을 그대로 사용자에게 보여준다.
이후 본 문서에 등장하는 `${SESSION_DIR}` 는 위에서 생성된 절대 경로다.
모든 상태 파일은 `${SESSION_DIR}` 하위에만 작성한다. `.claude/state/` 직하에는 절대 쓰지 않는다.

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
  "version": 3,
  "session_id": "<SESSION_ID>",
  "session_dir": "<SESSION_DIR>",
  "command": "fix",
  "intake_mode": "<manual | build | crash>",
  "step_id": 1,
  "updated_at": "<현재 시각 ISO 8601>",
  "status": "INIT",
  "attempt_count": 0,
  "allowed_to_modify": [],
  "forbidden_rules": [
    {"type": "glob", "value": "<project.json 의 forbidden_globs 를 그대로 옮긴다>"}
  ],
  "risk_flags": [],
  "risk_level": "LOW",
  "human_gate_required": false,
  "runtime_observable": null,
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

`${SESSION_DIR}/intake.json`:
```json
{"mode": null, "summary": null, "error_lines": [], "suspected_files": [], "runtime_observable": null,
 "issue_id": null, "title": null, "stack_trace": null, "crash_point": null,
 "app_version": null, "event_count": 0}
```

`${SESSION_DIR}/implementer.json`:
```json
{"recent_patches": []}
```

`${SESSION_DIR}/builder.json`:
```json
{"build_success": null, "error_hash": null, "error_files": [], "error_confidence": null}
```

`${SESSION_DIR}/runner.json`:
```json
{"skipped": null, "no_flow": null, "install_success": null, "replay_success": null, "failed_flow": null, "screenshot_path": null, "gate_error": null}
```

`${SESSION_DIR}/triage.json`:
```json
{"category": null, "confidence": null, "next_action": null, "suspected_files": []}
```

`runtime_observable` 주의: 이 값은 런타임 게이트의 오인 통과를 막는 근거다.
버그가 런타임 시나리오(화면 조작, API 호출, 명령 실행)로 확인 가능하면 true, 내부 로직처럼 시나리오로 닿지 않으면 false 다.
0단계에서 채우고, 3.5단계 판단에서 사용한다.

---

## 에이전트 결과 저장

explorer, builder, triage 는 결과 파일을 직접 쓰지 않는다. 소스를 못 고치게 도구에서 쓰기 권한을 뺐기 때문이다.
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
| triage | `triage.json` | `step_id,category,confidence,next_action,suspected_files` |

exit 1 (json 없음, 깨짐, 필수 키 누락) 이면 저장하지 않는다. 같은 에이전트를 한 번 재호출하며
"결과를 최종 메시지 끝의 json 블록으로 반환하라" 고 다시 요구한다. 두 번째도 실패하면 Human Gate 다.
json 을 손으로 고쳐 저장하지 않는다. 뒤 단계가 이 필드로 분기하므로 추측한 값은 엉뚱한 분기를 만든다.

## 0단계: 인테이크 (INTAKE)

orchestrator.json 의 status 를 "INTAKE" 로, intake_mode 를 아래 판정 결과로 업데이트한다.

이 호출의 인자 (치환된 값. 비어 있을 수 있다):

```
$ARGUMENTS
```

모드 판정 (위 인자 기준):
- 인자에 `--crash` 가 있으면 `crash`
- 인자에 `--build` 가 있으면 `build`
- 그 외(빈 인자 포함)는 `manual`

주의: `$ARGUMENTS` 는 로드 시점에 실제 인자로 치환된다. 그래서 판정 규칙 문장 안에 두면
치환 후 문장이 깨진다(인자가 비면 규칙이 통째로 사라진다). 위처럼 항상 데이터 줄로만 쓴다.

**세 모드 중 하나만 실행한다. 완료 후 모두 1단계로 합류한다.**

### 모드 A: manual (기본)

위 인자 또는 대화 맥락에서 버그 설명을 가져온다.

`intake.json` 을 채운다:
- `mode`: "manual"
- `summary`: 버그 설명 원문
- `runtime_observable`: 런타임 시나리오(화면 조작, API 호출, 명령 실행)로 확인 가능한 버그면 true, 아니면 false
  (판단이 애매하면 false 로 둔다. 게이트가 NO_FLOW 로 통과시키므로 막지 않는다)

설명이 비어 있으면 사용자에게 무엇을 고칠지 묻고 대기한다.

### 모드 B: build (컴파일/lint 에러)

에러 내용을 먼저 확보하기 위해 **builder 에이전트를 호출한다.**
호출 프롬프트 상단에 반드시 다음 한 줄을 명시한다:

```
session_dir: <SESSION_DIR>
```

완료 후 반환을 「에이전트 결과 저장」대로 `${SESSION_DIR}/builder.json` 에 저장하고 읽는다.

- `build_success == true` 면 수정할 대상이 없다. `status: "NO_TARGET"`,
  `termination_reason: "NO_BUILD_ERROR"` 로 기록하고 「종료 처리 > 대상 없음」 형식으로 보고한 뒤 끝낸다
- 실패면 `intake.json` 을 채운다:
  - `mode`: "build"
  - `summary`: 에러 요약 첫 줄
  - `error_lines`: builder.json 의 raw_error_lines
  - `suspected_files`: builder.json 의 error_files (참고용)
  - `runtime_observable`: false (컴파일 에러는 런타임 시나리오로 관찰할 대상이 아니다)

### 모드 C: crash (크래시 리포팅 연동)

크래시 인테이크는 **선택 기능이다.** 바인딩은 project.json 의 `crash_provider` 에 있다.

```
kind                    none 이면 이 모드는 설정되지 않은 것이다
app_id                  조회 대상 앱/서비스 식별자
source_package_prefix   우리 코드로 인정할 패키지/모듈 접두사
issue_tool              이슈 목록 조회 도구 이름
events_tool             이벤트(스택트레이스) 조회 도구 이름
```

**C-0. 설정 확인 (먼저 한다)**

`crash_provider.kind` 가 `none` 이거나 도구 이름이 비어 있으면 **여기서 멈춘다.**
`status: "NO_TARGET"`, `termination_reason: "CRASH_NOT_CONFIGURED"` 로 기록하고
"이 프로젝트에는 크래시 인테이크가 설정되지 않았다" 고 보고한 뒤 끝낸다.
존재하지 않는 도구를 부르거나 다른 인테이크로 몰래 바꾸지 않는다.

**C-1. 이슈 목록 조회**

`issue_tool` 을 호출한다 (appId = `crash_provider.app_id`, 상위 이슈 10개).
결과가 비어 있으면 조회 기간을 최근 30일로 확장해 재시도한다.
그래도 없으면 `status: "NO_TARGET"`, `termination_reason: "NO_CRASH_ISSUE"` 로 기록하고
「종료 처리 > 대상 없음」 형식으로 보고한 뒤 끝낸다.

**C-2. 이슈 선택**

위 인자에 이슈 ID 가 있으면 바로 사용한다.
없으면 상위 5개를 발생 횟수와 영향 사용자 수와 함께 보여주고 사용자 선택을 받는다.

**C-3. 스택트레이스 조회**

`events_tool` 을 호출한다 (appId, 선택된 이슈 ID, 최근 이벤트 3개).
가장 최근 이벤트의 스택트레이스를 사용한다.

**C-4. 스택트레이스 파싱**

1. `suspected_files`: `crash_provider.source_package_prefix` 로 시작하는 라인만 추출한다
   - 그 접두사 밖(런타임/표준 라이브러리/서드파티)은 우리 코드가 아니므로 무시한다
   - 각 라인에서 파일명과 라인번호를 뽑는다
   - 주의: 앱 식별자와 소스 패키지는 다를 수 있다. 접두사는 **소스 패키지** 기준으로 설정한다
2. `crash_point`: 스택트레이스 최상단의 우리 코드 라인 (실제 발생 지점)

**C-5. intake.json 업데이트**

- `mode`: "crash"
- `summary`: 이슈 제목
- `issue_id` / `title` / `stack_trace`(원문 전체) / `crash_point` / `app_version` / `event_count`
- `suspected_files`: C-4 추출 결과
- `runtime_observable`: 크래시 지점에 시나리오로 닿을 수 있으면(화면 계층, 요청 처리 경로) true, 아니면 false

---

## 1단계: 탐색 (EXPLORING)

orchestrator.json 의 status 를 "EXPLORING" 으로, `runtime_observable` 을 intake.json 값으로 업데이트한다.

**explorer 에이전트를 호출한다.**
호출 프롬프트 상단에 반드시 다음 한 줄을 명시한다:

```
session_dir: <SESSION_DIR>
```

추가 전달 정보 (모드 무관, intake.json 에서 그대로 가져온다):
- `summary` (무엇을 고쳐야 하는가)
- `error_lines` (있으면)
- `stack_trace` 와 `crash_point` (있으면. crash_point 는 라인번호 포함해 전달한다)
- `suspected_files` (있으면. 이 파일들을 우선 분석하도록 명시한다)
- 현재 step_id

에이전트 완료 후 반환을 「에이전트 결과 저장」대로 `${SESSION_DIR}/explorer-proposal.json` 에 저장하고 읽는다.

### Orchestrator 판단: proposal 검증

1. proposal.step_id 가 현재 step_id 와 다르면 explorer 를 재호출한다.

2. forbidden_rules 적용:
   - proposed_allowed_to_modify 에서 forbidden_rules 에 걸리는 파일을 제거한다
   - glob 패턴은 파일명에 직접 대조하여 필터링한다
   - 제거된 파일이 있으면 human_gate_required 를 true 로 설정한다

3. orchestrator.json 을 업데이트한다:
   ```
   allowed_to_modify: 필터링된 파일 목록
   risk_flags: proposal 의 risk_flags
   risk_level: proposal 의 risk_level
   last_explorer_step: 현재 step_id
   status: "IMPLEMENTING"
   ```

4. risk_level 이 "HIGH" 이면 → Human Gate 발동

---

## 2단계: 수정 (IMPLEMENTING)

orchestrator.json 의 status 를 "IMPLEMENTING" 으로 업데이트한다.
attempt_count 를 1 증가시킨다.

**종료 조건 사전 검사:**
- attempt_count >= 5 → FAILED_MAX_ITER 로 종료

**implementer 에이전트를 호출한다.**
호출 프롬프트 상단에 반드시 다음 한 줄을 명시한다:

```
session_dir: <SESSION_DIR>
```

추가 전달 정보:
- intake.json 의 `summary` (수정 방향 컨텍스트)
- `stack_trace` 와 `crash_point` (있으면)
- 빌드 에러 내용 (재호출인 경우 builder.json 에서)

**코드 출력 금지 규칙 (필수):**
- 변경 코드를 응답 텍스트에 출력하지 않는다
- 모든 코드 변경은 Write/Edit 도구로 파일에 직접 반영한다
- 대용량 파일은 500줄 이하 단위로 나눠 여러 번의 Write/Edit 로 작성한다

에이전트 완료 후 `${SESSION_DIR}/implementer.json` 을 읽는다.

### Orchestrator 판단: 수정 내용 검증

recent_patches 의 최신 항목을 확인한다. 네 검사는 LLM 이 "고쳤다" 고 하면서 실제로는
아무것도 바꾸지 않거나 같은 자리를 맴도는 실패 모드를 막는다.

1. `changed_lines == 0` → FAILED_MEANINGLESS_DIFF 로 종료
2. 최신 항목과 이전 항목의 `diff_hash + target_files_sorted` 가 동일하면 → FAILED_MEANINGLESS_DIFF 로 종료
3. 최근 3개 패치의 `changed_lines` 가 모두 3 미만이면 → FAILED_MEANINGLESS_DIFF 로 종료
4. 최근 3개 패치의 `target_files_sorted` 가 모두 동일하면 → human_gate_required: true 설정 후 Human Gate 발동

---

## 3단계: 빌드 (BUILDING)

orchestrator.json 의 status 를 "BUILDING" 으로 업데이트한다.

**builder 에이전트를 호출한다.**
호출 프롬프트 상단에 반드시 다음 한 줄을 명시한다:

```
session_dir: <SESSION_DIR>
```

에이전트 완료 후 반환을 「에이전트 결과 저장」대로 `${SESSION_DIR}/builder.json` 에 저장하고 읽는다.

### Orchestrator 판단: 빌드 결과

**빌드 성공 시:**
곧바로 SUCCESS 로 종료하지 않는다. 3.5단계(런타임 게이트)로 진행한다.
런타임 게이트가 통과(또는 SKIP / NO_FLOW)해야 SUCCESS 다.
빌드 통과는 컴파일 성공일 뿐 동작 보장이 아니기 때문이다.

**빌드 실패 시:**

1. error_hash 가 last_error_hash 와 동일하면 same_error_count 를 1 증가시킨다.
   다르면 same_error_count 를 1로 초기화하고 last_error_hash 를 업데이트한다.
2. same_error_count >= 3 → FAILED_SAME_ERROR 로 종료
3. error_confidence 별 판단:
   - LOW: explorer 재실행 필요 (1단계로 복귀, step_id 증가)
   - LOW 2회 연속: human_gate_required: true, Human Gate 발동
   - MEDIUM: 2단계로 복귀
   - HIGH + error_files 가 allowed_to_modify 밖: explorer 재실행 (1단계로 복귀)
   - HIGH + error_files 가 allowed_to_modify 안: 2단계로 복귀
4. step_id 를 1 증가시키고 orchestrator.json 을 업데이트한 뒤 해당 단계로 복귀한다.

---

## 3.5단계: 런타임 게이트 (RUNTIME)

빌드 성공 후 실행한다. 빌드 통과를 실제 화면 동작으로 검증한다 (수정 후 1회).
`/fix` 는 시나리오로 닿지 않는 버그(내부 로직, 파서 등)도 다루므로 런타임 게이트는 기회주의적이다.
UI 로 관찰 가능한 버그일 때만 의미가 있고, 아니면 NO_FLOW 로 통과시킨다 (막지 않는다).
시나리오 작성 절차는 project.json 의 `docs.e2e_guide` 문서를 따른다 (없으면 기존 시나리오를 본떠 쓴다).

orchestrator.json status 를 "RUNTIME" 으로 업데이트한다.

### 시나리오 준비 (선택)

E2E 시나리오 디렉토리는 project.json 의 `e2e.dir` 이다.

- 관련 시나리오가 이미 있으면 그대로 사용한다.
- 없고 `runtime_observable == true` 이고 재현율이 "항상" 이면 수정된 동작을 검증하는 시나리오를 작성한다.
- `runtime_observable == false` 이거나 재현율이 "가끔 / 특정 조건" 이면 만들지 않는다 (게이트는 NO_FLOW 로 통과).

수정 전 실패 증명은 강제하지 않는다. 버그 수정의 기준은 "수정 후 재현 불가 확인" 이기 때문이다.

**버그를 고쳤으면 그 버그의 재발을 막는 assert 를 시나리오에 남긴다.**
새로 만들 때는 파일의 태그를 아래에서 산출한 TAGS 와 반드시 일치시킨다.
어긋나면 태그 매칭에서 빠져 NO_FLOW 로 오인 통과한다.

### 게이트 실행

선택적 재생: 바뀐 파일(allowed_to_modify)로부터 도메인 태그를 산출해 해당 도메인 시나리오만 재생한다.
공유 코드 변경이면 ALL 이 나와 전체를 회귀한다.

runtime_gate.sh 의 2번째 인자는 시나리오 경로가 아니라 프로젝트 경로다. 빈 문자열을 넘기면
스크립트가 자기 위치(.claude/scripts)에서 워크트리 루트를 산출한다. 워크트리마다 .claude 가
따로 복사되므로 이 방식이 항상 옳다. flow 선택은 3번째 인자 태그로만 이뤄진다.

```bash
TAGS=$(python3 .claude/scripts/domains_for.py <allowed_to_modify 의 파일 경로들>)
bash .claude/scripts/runtime_gate.sh "${SESSION_DIR}" "" "$TAGS"
```

완료 후 `${SESSION_DIR}/runner.json` 을 읽는다.

### Orchestrator 판단

| runner.json | 판단 |
|---|---|
| gate_error != null | 게이트 자체가 못 돎 (설정 누락/경로 오설정/배포 실패). 통과 아님. 즉시 Human Gate |
| skipped=true | SKIP. 사용자 보고 후 SUCCESS (기기 미연결) |
| no_flow=true **이고 runtime_observable=false** | 런타임 커버리지 없음. 보고 후 SUCCESS (시나리오로 볼 수 없는 버그. 막지 않음) |
| no_flow=true **이고 runtime_observable=true** | **오인 통과.** 통과로 처리하지 않는다 (아래 참조) |
| replay_success=true | SUCCESS (수정 후 동작 검증됨) |
| replay_success=false | triage 호출 (아래) |

**오인 통과 방어 (필수).**
UI 로 관찰 가능한 버그인데 `no_flow=true` 가 나왔다면 둘 중 하나다:
(a) 그 도메인에 시나리오가 아예 없다 → 시나리오 준비 단계로 돌아가 최소 1개를 작성한다
(b) 작성한 시나리오의 태그가 TAGS 와 어긋나 매칭이 0이 됐다 → 태그를 TAGS 와 일치시킨다
어느 쪽이든 통과시키지 않는다. 이것이 게이트가 조용히 초록불만 켜는 것을 막는 방어다.
작성이 불가능한 사정이 있으면 SUCCESS 대신 사용자에게 보고하고 판단을 받는다.

`no_flow` 는 무조건 통과가 아니다. `/fix` 는 시나리오로 볼 수 없는 버그일 때만 통과다. 위 표의 runtime_observable 조건이 그 구분이다.

### replay 실패 시 triage 호출

runtime_attempt_count 를 1 증가시킨다.
**triage 에이전트를 호출한다** (프롬프트 상단에 session_dir 명시).
완료 후 반환을 「에이전트 결과 저장」대로 `${SESSION_DIR}/triage.json` 에 저장하고 읽어 category 에 따라 분기한다:

| category | next_action | 동작 | 종료 조건 |
|---|---|---|---|
| REAL_BUG | REINVOKE_IMPLEMENTER | 2단계 재호출, suspected_files 전달, attempt_count++ | 같은 화면 3연속 실패 → Human Gate |
| FLAKY | RETRY_REPLAY | flaky_retry_count++ 후 게이트 재시도 | 2회 초과 → Human Gate |
| FLOW_ERROR | FIX_FLOW | flow_fix_count++ 후 시나리오 수정 → 재시도 | 2회 초과 → Human Gate |
| ENV_STATE | HUMAN_GATE | 미인증/권한/실행 대상 상태. 사람 개입 | 즉시 |

last_triage_category 를 기록한다. confidence 가 LOW 이면 next_action 을 HUMAN_GATE 로 올린다.
REINVOKE_IMPLEMENTER 분기는 2단계로 돌아가며 기존 종료조건(attempt_count >= 5)이 동일 적용된다.

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

## Human Gate 절차

human_gate_required 가 true 가 된 상황:

1. orchestrator.json 의 status 를 "HUMAN_GATE" 로 업데이트한다
2. 현재 상태를 사용자에게 보고한다:
   - SESSION_ID 와 SESSION_DIR
   - 왜 Human Gate 가 발동됐는지
   - 현재 단계(status)와 intake_mode
   - 현재 allowed_to_modify 목록
   - risk_flags 및 risk_level
   - 지금까지 시도한 내용 요약
   - intake_mode 가 crash 면 크래시 이슈 정보 (issue_id, title, crash_point)
3. 사용자의 지시를 기다린다

---

## 종료 처리

### 종료 상태 정의 (필수)

`orchestrator.json` 의 `status` 와 `termination_reason` 은 아래 값만 쓴다.
**정의에 없는 값을 지어내지 않는다.** 실행마다 이름이 갈리면 `metrics.py` 집계에서 같은 결과가
다른 항목으로 세어진다. 새 종료 사유가 생기면 코드에서 지어내지 말고 이 표에 먼저 추가한다.

| status | termination_reason | 의미 | 뒤처리 |
|---|---|---|---|
| `SUCCESS` | `null` | 수정하고 게이트까지 통과(또는 SKIP / 정당한 NO_FLOW) | 아래 「성공」 |
| `NO_TARGET` | `NO_BUILD_ERROR` | build 모드인데 빌드가 이미 성공. 고칠 대상 없음 | 아래 「대상 없음」 |
| `NO_TARGET` | `NO_CRASH_ISSUE` | crash 모드인데 해당 기간 크래시 이슈 없음 | 아래 「대상 없음」 |
| `NO_TARGET` | `CRASH_NOT_CONFIGURED` | crash 모드인데 crash_provider 미설정 | 아래 「대상 없음」 |
| `FAILED_MAX_ITER` | 동일 | attempt_count >= 5 | 아래 「실패」 |
| `FAILED_SAME_ERROR` | 동일 | same_error_count >= 3 | 아래 「실패」 |
| `FAILED_MEANINGLESS_DIFF` | 동일 | 무의미 diff 검사 1~3 에 걸림 | 아래 「실패」 |
| `ABORTED_BY_USER` | 동일 | 사용자가 중단 지시 | 아래 「실패」 형식으로 보고 |
| `HUMAN_GATE` | `null` | **종료가 아니다.** 사람 판단 대기 | 「Human Gate 절차」 |

`NO_TARGET` 을 `SUCCESS` 로 적지 않는다. 둘은 다른 사건이다 — 전자는 아무것도 안 고쳤고,
후자는 고치고 검증까지 마쳤다. 섞으면 "게이트 통과율" 이 인테이크 공회전으로 부풀려진다.
같은 이유로 `NO_TARGET` 은 실패도 아니다. 파이프라인은 정상 동작했다.

### 대상 없음 (NO_TARGET)

인테이크에서 고칠 대상이 없어 1단계로 가지 않고 끝난 경우다. explorer 이후는 실행되지 않는다.

```
SESSION_ID: <SESSION_ID>
인테이크: [build / crash]
결과: 고칠 대상 없음 ([NO_BUILD_ERROR] 빌드 성공 / [NO_CRASH_ISSUE] 크래시 이슈 없음 / [CRASH_NOT_CONFIGURED] 크래시 연동 미설정)
소요: [빌드 시간 등]
```

코드를 건드리지 않았으므로 documenter 도 호출하지 않는다.

### 성공 (SUCCESS)
- SESSION_ID 보고
- 수정된 파일 목록 보고
- 빌드 성공 확인
- 런타임 게이트 결과 보고 (통과 / SKIP / NO_FLOW 중 무엇이었는지 명시)
  NO_FLOW 였으면 "런타임 커버리지 없음" 을 명시해 사일런트 통과로 오인되지 않게 한다
- documenter 호출 여부는 변경 규모에 따라 판단한다
  (클래스 추가/삭제, 언어 전환, 주요 로직 변경 시 documenter 호출, session_dir 인자 전달.
   함께 넘긴다: `changed_files` (recent_patches 의 target_files_sorted 합집합), `domains` (게이트에 넘긴 TAGS).
   단순 컴파일 에러 수정은 문서화 불필요)
- **intake_mode 가 crash 인 경우에만**: 크래시 이슈에 수정 완료 노트를 추가할지 사용자에게
  확인 후 진행한다 (`crash_provider` 가 노트 도구를 제공할 때만).
  외부 시스템 쓰기이므로 확인 없이 진행하지 않는다

### 실패 (FAILED_*)
orchestrator.json 의 termination_reason 을 업데이트하고 보고한다:

```
SESSION_ID: <SESSION_ID>
인테이크: [manual / build / crash]  (crash 면 [issue_id] [title] 추가)
종료 이유: [FAILED_MAX_ITER / FAILED_SAME_ERROR / FAILED_MEANINGLESS_DIFF / ABORTED_BY_USER]
현재 단계: <status>
시도 횟수: N회
마지막 에러: [에러 요약]
권장 행동: [수동으로 확인이 필요한 사항]
```
