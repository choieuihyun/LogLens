# adapters

스택별 명령 묶음. `core/` 는 여기서 명령을 읽어 쓰므로 스택이 바뀌어도 로직은 그대로다.

어댑터 하나가 답하는 질문은 여섯이다. 프로젝트가 일부만 바꾸려면 어댑터 파일을 고치지 않고 `project.json` 의 `adapter_override` 에 적는다.

| 키 | 뜻 |
|---|---|
| `build` | 어떻게 컴파일하나 |
| `deploy` | 어디에 올리나 (없으면 null). 서버라면 준비될 때까지 기다리는 것까지 포함한다 (`--wait`, 헬스체크) |
| `teardown` | 올린 것을 어떻게 내리나 (없으면 null). 게이트가 어느 경로로 끝나든 부른다 |
| `smoke` | 켜지는지만 어떻게 확인하나 |
| `logs` | 실패했을 때 앱이나 서버 로그를 어떻게 보나 (`{"command": ...}`, 없으면 null). triage 가 근거로 쓴다 |
| `e2e` | 동작을 어떻게 재생하나 |

`e2e` 안에서 스택마다 문법이 갈리는 곳:

| 키 | 뜻 | 예 |
|---|---|---|
| `command` | 재생 명령. `{REPORT_XML}` 자리에 JUnit 리포트를 **파일로** 남겨야 한다. 화면에만 찍으면 게이트는 결과를 못 읽는다 | playwright 는 `PLAYWRIGHT_JUNIT_OUTPUT_NAME` 으로 경로를 준다 |
| `tag_option` | 태그로 좁힐 때 붙는 옵션. `{TAGS}` 자리에 태그가 들어간다 | `--include-tags={TAGS}` |
| `tag_join` | 태그 여러 개를 잇는 구분자. 생략하면 콤마 | playwright 는 정규식이라 `\|`, pytest 는 ` or ` |
| `error_patterns` | (선택, `e2e` 밖 최상위) 빌드 에러에서 파일과 줄을 뽑는 정규식 목록. `file`, `line` 이름 그룹 필수. 흔한 형식(파일:줄, 파일(줄,열), File "x", line n)은 기본으로 읽으므로 그 밖의 형식만 적는다 | `"(?P<file>\\S+\\.vue)@(?P<line>\\d+)"` |
| `tag_scan` | 시나리오 파일에서 태그를 읽는 규칙. import 경로 같은 것이 태그로 잡히지 않게 한다 | `@playwright/test` 가 도메인 `playwright` 로 잡히면 안 된다 |

| 어댑터 | 대상 | 상태 |
|---|---|---|
| `android-gradle-maestro.json` | 안드로이드 앱 | 실제 프로젝트에서 검증됨 |
| `node-vite-playwright.json` | 웹 앱 | 가짜 러너로 게이트 완주 확인. 실전 완주 전 |
| `python-pytest.json` | 파이썬 서버, 라이브러리 | 스키마만 맞춤. 실전 완주 전 |

대상은 모든 프로젝트다 (저장소 README 의 대상 범위 참고). 목록에 없는 스택은 이 형식으로 어댑터를 새로 쓴다.
올리기가 없는 유형은 `deploy` 를, 실행 대상 개념이 없는 유형은 `device` 를 null 로 둔다.
