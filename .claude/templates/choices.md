# 선택지 목록

`core/` 는 어느 스택도, 어느 아키텍처도 전제하지 않는다. 대신 세팅할 때 사용자가 고를 수 있게 여기 모아 둔다.
세팅하는 AI 는 이 목록을 **제안으로만** 쓴다. 코드 스캔으로 추측한 것을 먼저 보여 주고 사용자가 고른다.
목록에 없는 답도 받는다. 목록은 출발점이지 제한이 아니다.

core 를 일반화하면서 걷어 낸 스택 전용 규칙도 버리지 않고 여기로 옮겼다. 그 스택을 쓰는 프로젝트는 그대로 가져가면 된다.

각 항목의 "저장 위치" 는 사용자가 고른 답이 들어갈 곳이다.

---

## 프로젝트 유형

| 선택지 | 게이트의 올리기 | 시나리오 | `project.has_ui` |
|---|---|---|---|
| 모바일 앱 | 기기에 설치 | 화면 조작 | true |
| 웹 앱 | 미리보기 서버 | 브라우저 조작 | true |
| 데스크톱 앱 | 실행 파일 기동 | 화면 조작 | true |
| 서버, API | 서버 기동 (프로세스, 컨테이너) + 내리기 | API 호출 | false |
| 라이브러리 | 없음 | 통합 테스트 | false |
| CLI | 없음 | 명령 실행 | false |

저장 위치: `project.has_ui`, 어댑터 선택

## 테스트 도구 (시나리오 재생)

게이트는 결과를 JUnit XML 로 읽는다. 도구는 무엇이든 되고, JUnit 을 쓰게 하는 방법은 세팅하는 AI 가 어댑터에 넣는다.

| 유형 | 선택지 | JUnit 출력 |
|---|---|---|
| 모바일 | maestro, Espresso, XCUITest, Detox, Appium | 대부분 기본 제공 |
| 웹 | playwright, cypress, webdriverio | playwright 는 `PLAYWRIGHT_JUNIT_OUTPUT_NAME`, cypress 는 junit 리포터 |
| 서버, 라이브러리 | pytest, vitest, jest, go test, cargo test, JUnit, RSpec | jest 는 `jest-junit`, go 는 `gotestsum`, cargo 는 `nextest` |

저장 위치: `adapters/<이름>.json` 의 `e2e`

## UI 자동화 식별자 속성

| 스택 | 속성 |
|---|---|
| Jetpack Compose | `testTag` |
| Android View | `resource-id` (contentDescription 은 접근성 용도라 피한다) |
| React Native | `testID` |
| 웹 | `data-testid`, `data-test`, `data-cy` |
| SwiftUI, UIKit | `accessibilityIdentifier` |
| Flutter | `Key` |

저장 위치: `ui_test_id`

## 아키텍처 패턴

implementer 와 planner 는 "프로젝트에 없는 패턴을 새로 들이지 않는다" 만 안다. 무엇을 쓰는지는 여기서 골라 컨벤션 문서에 적는다.

| 계열 | 선택지 |
|---|---|
| 모바일, 데스크톱 UI | MVVM, MVI, MVP, MVC, Clean Architecture, TCA |
| 웹 프런트 | 컴포넌트 + 전역 store, Flux/Redux, 서버 컴포넌트 중심, feature-sliced |
| 서버 | 계층형 (controller, service, repository), 헥사고날, 클린, CQRS |

고른 뒤 함께 정할 것:
- 기존 코드가 이 패턴을 안 따르는 곳이 있다면 "고쳐 가며 맞춘다" 인가 "주변을 따른다" 인가
- 새 패턴 도입 금지의 범위 (예: "ViewModel 없는 화면에 ViewModel 을 새로 만들지 않는다")

저장 위치: `docs.conventions` 가 가리키는 문서

## 공유 상태 전파 경로 (위험 축 EVENT)

| 계열 | 선택지 |
|---|---|
| 앱 | 이벤트 버스, 관찰 가능한 상태 (Flow, LiveData, Combine), 브로드캐스트 |
| 웹 | 전역 store (Redux, Zustand, Pinia), context, 이벤트 emitter, 서버 상태 캐시 (React Query 등) |
| 서버 | 메시지 큐 (Kafka, RabbitMQ, SQS), 도메인 이벤트, pub/sub, 웹소켓 브로드캐스트 |
| 없음 | 프로젝트에 전파 경로가 없다. EVENT 관련 검사는 "해당 없음" 이 된다 |

그 경로의 파일은 `risk_globs` 에 넣는다. 건드리면 파급이 크다.

저장 위치: `risk_globs`, 컨벤션 문서

## 위험 축별 이 프로젝트의 뜻

축 이름(SYNC, EVENT, THREAD, DB, LIST)은 고정이다. 무엇이 해당하는지만 프로젝트가 정한다.

| 축 | 물을 것 |
|---|---|
| SYNC | 같은 상태가 여러 기기, 세션, 인스턴스에 동시에 있는가. 원본은 서버인가 로컬인가 |
| EVENT | 위 "공유 상태 전파 경로" |
| THREAD | UI 스레드나 요청 처리 스레드를 막을 수 있는 작업이 어디 있는가 (앱은 코루틴, 스레드 풀 / 서버는 워커, 비동기 작업) |
| DB | 영속 저장소가 무엇인가 (Room, SQLite, IndexedDB, Postgres, MySQL, 파일) |
| LIST | 부분 갱신이나 페이지 단위 조회를 하는 목록이 있는가 |

저장 위치: `risk_globs`, 컨벤션 문서

## 빌드 에러 형식

builder 는 에러에서 파일과 줄을 뽑아 신뢰도를 매긴다. 형식이 스택마다 달라서 여기서 고른다.

| 도구 | 형식 예 |
|---|---|
| javac, kotlinc, gcc, go, rustc, eslint | `파일:줄:열` |
| tsc | `파일(줄,열)` |
| 안드로이드 리소스 처리, 매니페스트 병합 | 태스크 이름과 리소스 경로 |
| python | `File "파일", line 줄` |

저장 위치: 어댑터의 `error_patterns`. 공유 어댑터를 쓰면 `project.json` 의 `adapter_override.error_patterns`

## 에이전트에 붙일 MCP

필수가 아니다. `/setup` 이 에이전트 차례마다 "붙일 MCP 가 있나?" 를 한 번 묻는다. 없으면 넘어간다.
붙이면 에이전트 파일을 고치지 않고 `project.json` 의 `agent_tools` 에 도구 이름을 적는다. `apply_agent_tools.py` 가 반영하고, 재설치해도 다시 반영된다.

읽기 전용 에이전트에는 조회 도구만 붙인다. 쓰기 도구를 붙이면 소스를 못 고치게 막아 둔 장치가 무너진다.

| 에이전트 | 붙일 만한 것 |
|---|---|
| explorer | 코드 심볼 검색 (LSP, 코드 인덱스 서버), 이슈 트래커 조회 |
| triage | 로그 수집 서버, 에러 추적 서비스, 브라우저 콘솔 조회 |
| discuss, spec | 이슈 트래커, 기획 문서, 디자인 도구 조회 |
| planner, tutor | 라이브러리 문서 서버 (공식 문서를 검색 대신 직접 조회) |
| builder | CI 로그 조회 (원격에서만 빌드되는 프로젝트) |
| documenter | 노트 앱, 사내 위키 쓰기 (`docs.vault_prefix` 와 함께) |
| implementer, plan-checker, verifier | 붙이지 않는다 |

`/fix --crash` 의 크래시 인테이크도 MCP 를 쓴다. 이것은 에이전트가 아니라 `/fix` 가 직접 부르므로 `crash_provider` 에 적는다.

## 코드 스타일

implementer 는 스타일 규칙을 컨벤션 문서에서 읽는다. 자주 나오는 선택지:

- 주석과 로그의 언어, 특수문자 허용 여부
- import 정렬, 전체 경로 이름 금지
- 이름 규칙 (UI 식별자는 snake_case 등)

저장 위치: `docs.conventions` 가 가리키는 문서
