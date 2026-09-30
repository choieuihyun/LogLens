#!/usr/bin/env bash
# 런타임 게이트 (배포 + E2E 재생)
# 역할: 빌드 산출물을 실행 대상에 올리고 E2E 시나리오를 재생한 뒤 결과를 runner.json 에 기록한다.
# 성격: 결정적 셸 단계. LLM 미개입 (토큰 0). 실패 분류는 triage 가 별도로 한다.
#
# 무엇을 어떤 명령으로 하는지는 이 파일이 모른다. 어댑터(adapters/<이름>.json)와
# project.json 이 정하고, 여기서는 순서와 판정만 담당한다.
# 스택이 바뀌어도 이 파일은 그대로다. 그것이 이 분리의 목적이다.
#
# 사용법: runtime_gate.sh <session_dir> [project_dir] [tags]
#   project_dir: 비우면 이 스크립트 위치(.claude/scripts)에서 워크트리 루트를 자동 산출한다.
#                .claude 는 워크트리마다 따로 복사되므로 자기 위치 기준이 항상 옳다.
#                하드코딩 기본값을 두면 워크트리를 옮겼을 때 죽은 경로를 조용히 참조한다.
#   tags: 콤마로 구분된 도메인 태그 (예: message,buddylist). 그 태그 시나리오만 재생한다.
#         비우거나 "ALL" 이면 전체를 재생한다 (전체 회귀).
#         domains_for.py 가 allowed_to_modify 로부터 산출한 값을 넘기면 된다.
#
# 종료 코드:
#   0  게이트 정상 수행 (replay 통과, 또는 SKIP, 또는 NO_FLOW)
#   1  replay 실패 (orchestrator 가 runner.json 읽고 triage 호출)
#   2  배포(install) 실패
#   3  인자/설정/환경 오류 (게이트 자체가 못 돌았음. 통과가 아니다)
#
# 어떤 경우든 runner.json 은 항상 기록한다. orchestrator 는 종료코드가 아니라 runner.json 을 신뢰한다.
# 게이트 자체가 못 돈 경우는 runner.json 의 gate_error 에 사유가 들어간다 (통과로 읽으면 안 된다).
# 설정이 없을 때 조용히 SKIP(0) 으로 끝내면 안 된다. 그것은 초록불로 읽힌다.

set -u

SESSION_DIR="${1:-}"

if [ -z "$SESSION_DIR" ]; then
  echo "ERROR: session_dir 인자 누락. 사용법: runtime_gate.sh <session_dir> [project_dir] [tags]"
  exit 3
fi

# 이 스크립트의 실제 위치. 워크트리 루트는 .claude/scripts 에서 두 단계 위다.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# project_dir 은 명시적으로 넘어온 경우에만 존중하고, 비어 있으면 자기 위치 기준 루트를 쓴다.
PROJECT_DIR="${2:-}"
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="$REPO_ROOT"
TAGS="${3:-}"

# 세션 디렉토리를 절대경로로 고정한다. 아래에서 cd 하므로 상대경로면 산출물 경로가 어긋난다.
if ! mkdir -p "$SESSION_DIR" 2>/dev/null; then
  echo "ERROR: session_dir 생성 실패: $SESSION_DIR"
  exit 3
fi
SESSION_DIR="$(cd "$SESSION_DIR" && pwd)"

REPORT_XML="$SESSION_DIR/e2e-report.xml"
DEBUG_DIR="$SESSION_DIR/e2e-debug"

# 시나리오가 실제로 덮는 도메인 목록. 아래 2-0 에서 채운다.
# 그 전에 끝나는 경로(대상 미연결 등)에서는 빈 값이 남는다.
COVERAGE_DOMAINS=""
FULL_REGRESSION="false"

mkdir -p "$DEBUG_DIR"

# runner.json 기록 헬퍼 (python 으로 안전하게 JSON 작성)
# 인자: install_success replay_success skipped skip_reason no_flow e2e_exit [gate_error]
# parse_runner.py 는 project_dir 이 아니라 이 스크립트 옆에서 찾는다. project_dir 이 깨져도 기록은 남아야 한다.
#
# 누적 메트릭(runtime_metrics.jsonl)도 여기서 함께 남긴다.
# WHY: 게이트가 끝나는 모든 경로는 반드시 write_runner 를 거친다. 즉 여기가 유일한 길목이다.
#      기록을 커맨드 문서의 마지막 단계에 맡기면 LLM 이 거기까지 도달해야만 남는데, 실제로는
#      중간에 끝나는 경우가 많아 게이트를 27회 돌리고도 메트릭이 1줄만 쌓여 있었다.
#      결정적으로 도는 셸 쪽으로 옮겨야 측정이 실제로 이뤄진다.
#      record_metric.py 는 멱등이므로 커맨드 문서가 뒤에 다시 불러 triage 결과를 채워도 줄이 늘지 않는다.
#      기록 실패가 게이트 자체를 실패시키면 안 되므로 || true 로 삼킨다.
# 새 조기 종료 경로를 추가할 때도 반드시 이 함수를 거쳐야 한다. 우회하면 그 경로는 측정에서 사라진다.
write_runner() {
  RG_INSTALL="$1" RG_REPLAY="$2" RG_SKIPPED="$3" RG_SKIPREASON="$4" RG_NOFLOW="$5" RG_EEXIT="$6" \
  RG_GATEERR="${7:-null}" \
  RG_SESSION="$SESSION_DIR" RG_REPORT="$REPORT_XML" RG_DEBUG="$DEBUG_DIR" \
  RG_TAGS="${TAGS:-}" RG_COVERAGE="$COVERAGE_DOMAINS" RG_FULLREG="$FULL_REGRESSION" \
  python3 "$SCRIPT_DIR/parse_runner.py"

  python3 "$SCRIPT_DIR/record_metric.py" "$SESSION_DIR" "$TAGS" || true
}

# 0-0. 설정 로드 (project.json + 어댑터)
# 설정을 못 읽으면 게이트는 돌 수 없다. 이때 SKIP(0) 으로 끝내면 초록불로 오인되므로 exit 3 이다.
HC_OK=0
HC_ERROR="설정 로드 실패"
eval "$(python3 "$SCRIPT_DIR/harness_config.py" --export "$PROJECT_DIR" 2>/dev/null)"

# HC_OK=2 는 "이 프로젝트는 런타임 게이트를 쓰지 않는다" 는 명시적 선언이다.
# 통과(SUCCESS)가 아니라 SKIP 으로 기록한다. 보고에 그 사실이 남아야 초록불로 오인되지 않는다.
if [ "${HC_OK:-0}" = "2" ]; then
  echo "SKIP: 런타임 게이트가 꺼져 있음 (project.json 의 runtime_gate=false)."
  write_runner "null" "null" "true" "gate_disabled" "false" "null"
  exit 0
fi

if [ "${HC_OK:-0}" != "1" ]; then
  echo "ERROR: ${HC_ERROR:-설정 로드 실패}"
  echo "       .claude/project.json 을 채운다 (키 설명은 하네스의 templates/README.md)."
  write_runner "null" "null" "false" "null" "false" "null" "bad_config"
  exit 3
fi

if [ -n "${HC_MISSING:-}" ]; then
  echo "ERROR: 어댑터 명령에 안 채워진 빈칸이 있다: $HC_MISSING"
  echo "       project.json 의 vars 에 채운다. 반쪽 명령으로 실행하지 않는다."
  write_runner "null" "null" "false" "null" "false" "null" "unfilled_vars"
  exit 3
fi

E2E_DIR_REL="${HC_E2E_DIR:-}"
if [ -z "$E2E_DIR_REL" ]; then
  echo "ERROR: E2E 디렉토리가 정해지지 않았다 (project.json 의 e2e.dir 또는 어댑터 dir_default)"
  write_runner "null" "null" "false" "null" "false" "null" "bad_config"
  exit 3
fi
E2E_PATH="$PROJECT_DIR/$E2E_DIR_REL"

# 0-1. 프로젝트 경로 검증 (어댑터가 지정한 표식이 있어야 우리 워크트리다)
# 이 검사가 없으면 죽은 경로에서 시나리오를 못 찾아 NO_FLOW 로 빠지고, orchestrator 가 통과로 오인한다.
MARKER_OK="false"
for m in ${HC_MARKERS:-}; do
  if [ -e "$PROJECT_DIR/$m" ]; then MARKER_OK="true"; break; fi
done
if [ "$MARKER_OK" != "true" ]; then
  echo "ERROR: project_dir 이 유효한 워크트리가 아님 (표식 없음: ${HC_MARKERS:-미지정}): $PROJECT_DIR"
  write_runner "null" "null" "false" "null" "false" "null" "bad_project_dir"
  exit 3
fi

echo "게이트 대상 워크트리: $PROJECT_DIR (어댑터: ${HC_ADAPTER:-미지정})"

# 1. 실행 대상 연결 확인 (미연결 시 SKIP, 사일런트 통과 아님)
# 대상 개념이 없는 스택(어댑터의 device 가 null)은 이 단계를 건너뛴다.
if [ -n "${HC_DEVICE_CHECK:-}" ]; then
  DEVICE_COUNT=$(eval "${HC_DEVICE_CHECK}" 2>/dev/null | awk "${HC_DEVICE_FILTER:-1}" | wc -l | tr -d ' ')
  if [ "${DEVICE_COUNT:-0}" = "0" ]; then
    echo "SKIP: 실행 대상 미연결. 런타임 게이트 건너뜀."
    write_runner "null" "null" "true" "${HC_SKIP_REASON:-no_device}" "false" "null"
    exit 0
  fi
fi

# 2. 시나리오 존재 확인 (없으면 NO_FLOW, 통과로 처리하지 않음)
FLOW_COUNT=$(python3 "$SCRIPT_DIR/e2e_tags.py" --match "$E2E_PATH" "")
if [ "${FLOW_COUNT:-0}" = "0" ]; then
  echo "NO_FLOW: 재생할 E2E 시나리오가 없음. baseline 시나리오 작성 필요. ($E2E_PATH)"
  write_runner "null" "null" "false" "null" "true" "null"
  exit 0
fi

# 2-0. 시나리오가 실제로 덮는 도메인 산출 (거짓 PASS 방지. 자세한 사유는 e2e_tags.py 주석)
COVERAGE_DOMAINS=$(python3 "$SCRIPT_DIR/e2e_tags.py" --coverage "$E2E_PATH")

# 2-1. 선택적 재생 스코프 결정 (태그)
# TAGS 가 비었거나 "ALL" 이면 전체 회귀. 그 외엔 해당 태그 시나리오만 재생한다.
TAG_OPT=""
if [ -n "$TAGS" ] && [ "$TAGS" != "ALL" ]; then
  # 배포 전에 해당 태그 시나리오가 실제로 있는지 사전 점검 (없으면 배포 낭비 방지)
  TAG_MATCH=$(python3 "$SCRIPT_DIR/e2e_tags.py" --match "$E2E_PATH" "$TAGS")
  if [ "${TAG_MATCH:-0}" = "0" ]; then
    echo "NO_FLOW: 태그(${TAGS})에 해당하는 시나리오가 없음. 이 도메인은 런타임 커버리지 없음."
    write_runner "null" "null" "false" "null" "true" "null"
    exit 0
  fi
  # 도메인 태그는 콤마로 오지만 러너가 받는 구분자는 어댑터가 정한다 (tag_join).
  # 콤마를 그대로 넘기면 정규식으로 받는 러너에서는 아무 시나리오도 안 골라진다.
  JOINED_TAGS="${TAGS//,/${HC_TAG_JOIN:-,}}"
  TAG_OPT="${HC_TAG_OPT//\{TAGS\}/$JOINED_TAGS}"
  echo "선택적 재생: ${TAG_OPT} (해당 시나리오 ${TAG_MATCH}개)"
else
  FULL_REGRESSION="true"
  echo "전체 회귀: 시나리오 전체 재생 (TAGS=${TAGS:-없음}, 시나리오 ${FLOW_COUNT}개)"
  echo "  실제 커버 도메인: ${COVERAGE_DOMAINS:-알 수 없음}"
  echo "  주의: ALL 은 시나리오 전체를 돌릴 뿐 전 도메인을 검증한다는 뜻이 아니다."
  echo "        바꾼 파일의 도메인이 위 목록에 없으면 이 통과는 그 화면을 검증하지 않았다."
  echo "        (도메인 매핑을 못 해 ALL 로 떨어졌다면 project.json 의 domains 규칙을 보강한다.)"
fi

# 3. 배포 (컴파일은 builder 가 이미 통과시킨 상태. 여기서는 올리기만)
# 올린 것은 반드시 내린다. 서버나 컨테이너를 띄우고 그대로 끝내면 다음 게이트가 포트 충돌로 죽고,
# triage 는 그것을 환경 문제로 분류해 사람을 부른다.
# 그래서 배포를 시도하기 직전에 EXIT 트랩을 건다. 배포 실패, 재생 실패, 통과 어느 경로로 끝나도 내린다.
# 반쪽만 뜬 상태도 내려야 하므로 배포 성공 뒤가 아니라 시도 전에 건다.
# 내리기 실패는 게이트 판정을 바꾸지 않는다. 판정은 재생 결과이고, 내리기 실패는 로그로만 남긴다.
teardown() {
  [ -n "${HC_TEARDOWN_CMD:-}" ] || return 0
  echo "내리기 실행: $HC_TEARDOWN_CMD"
  ( cd "$PROJECT_DIR" && eval "$HC_TEARDOWN_CMD" ) 2>&1 | tail -10
  # tail 의 종료값이 아니라 내리기 명령의 값을 본다 (배포 판정과 같은 이유)
  [ "${PIPESTATUS[0]}" = "0" ] || echo "내리기 실패 (판정에는 영향 없음)"
}
if ! cd "$PROJECT_DIR"; then
  echo "ERROR: project_dir 이동 실패: $PROJECT_DIR"
  write_runner "null" "null" "false" "null" "false" "null" "bad_project_dir"
  exit 3
fi

trap teardown EXIT

if [ -n "${HC_DEPLOY_CMD:-}" ]; then
  echo "배포 실행: $HC_DEPLOY_CMD"
  # 종료값은 tail 이 아니라 배포 명령의 것을 본다. 파이프라인은 마지막 명령의 값을 돌려주므로
  # if ! eval ... | tail 로 쓰면 배포가 실패해도 tail 의 0 을 받아 설치 성공으로 기록된다.
  eval "$HC_DEPLOY_CMD" 2>&1 | tail -20
  DEPLOY_EXIT=${PIPESTATUS[0]}
  if [ "$DEPLOY_EXIT" != "0" ]; then
    echo "배포 실패 (exit $DEPLOY_EXIT)."
    write_runner "false" "null" "false" "null" "false" "null" "install_failed"
    exit 2
  fi
  INSTALL_RESULT="true"
else
  # 배포 단계가 없는 스택이다 (어댑터의 deploy 가 null). 없음과 실패를 구분해 기록한다.
  INSTALL_RESULT="null"
fi

# 4. E2E 재생 (JUnit 리포트 + 산출물 수집)
# 세션마다 달라지는 자리만 여기서 채운다. 명령 자체는 어댑터가 정한 것이다.
E2E_CMD="${HC_E2E_CMD}"
E2E_CMD="${E2E_CMD//\{E2E_PATH\}/$E2E_PATH}"
E2E_CMD="${E2E_CMD//\{TAG_OPT\}/$TAG_OPT}"
E2E_CMD="${E2E_CMD//\{REPORT_XML\}/$REPORT_XML}"
E2E_CMD="${E2E_CMD//\{DEBUG_DIR\}/$DEBUG_DIR}"

echo "E2E 재생 실행: $E2E_CMD"
eval "$E2E_CMD" 2>&1 | tail -30
E2E_EXIT=${PIPESTATUS[0]}

# 5. 결과 기록 (python 이 JUnit 파싱 + 실패 스크린샷 탐색 + runner.json 작성)
write_runner "$INSTALL_RESULT" "$([ "$E2E_EXIT" = "0" ] && echo true || echo false)" \
  "false" "null" "false" "$E2E_EXIT"

if [ "$E2E_EXIT" = "0" ]; then
  echo "replay 통과."
  exit 0
else
  echo "replay 실패. orchestrator 가 triage 호출 필요."
  exit 1
fi
