# /setup 기록

## 2026-09-30 (첫 세팅)

### 3단계: 프로젝트 뼈대

| 항목 | 값 | 비고 |
|---|---|---|
| `project.name` | LogLens | |
| `project.has_ui` | true | 뷰어 브라우저 화면(`viewer/loglens/web/`)을 화면으로 침 |
| `runtime_gate` | false | E2E 시나리오 없음. 단위 테스트만 있음. 자동 회귀 재생 없음 |
| `adapter_inline.build` | compileall(viewer, tools) → 뷰어 unittest → `gradlew -p lib compileKotlin compileTestKotlin` | 게이트 대신 빌드 단계에서 뷰어 회귀(216개)를 잡음. Python 타입 검사기 없음. 뷰어(Python)와 lib(Kotlin) 둘 다 대상으로 두기로 확인 |
| `error_patterns` | 안 씀 | kotlinc `파일:줄`, python `File "…", line N` 은 하네스 기본 패턴이 잡음 |
| `e2e.*` | 비움 | 게이트 끔 |
| `domains` | emitter, format, sources, server, web, analysis, config | `bin/` 복사본, `__init__`/`__main__`, 대상 불분명한 `test_table*`/`test_tree`/`test_tools` 는 ALL. `__pycache__` 는 shared |
| `forbidden_globs` | `bin/` 복사본, gradle 래퍼, `build/`, `__pycache__/`, `기획서.md`, `LICENSE` | 테스트 픽스처는 금지 안 함 (사용자 선택) |
| `crash_provider` | none | 연결된 Firebase MCP 에 Crashlytics 조회 도구 없음 |

### 4단계: 도메인 지식

| 항목 | 상태 |
|---|---|
| `docs.domain_map` | `docs/domains` |
| `format` | 작성 (`docs/domains/format/DOMAIN.md`, RECORD_FORMAT·DECISIONS 에서 추림). 문서에 없는 추가 함정은 "나중에" |
| emitter, sources, server, web, analysis, config | 안 함 |

### 5단계: 에이전트

| 에이전트 | 채운 것 |
|---|---|
| explorer | `risk_axes`(SYNC 형식 계약, EVENT SSE, THREAD, DB 파일 저장, LIST 버퍼·표), `risk_globs`, 보충 칸, MCP serena 읽기 도구 4개 |
| implementer | `docs.conventions` = `docs/CONVENTIONS.md` (새로 만듦, 기존 규칙만 모음), `ui_test_id` = `id`. 보충 없음 |
| builder | 보충 칸 (첫 gradle 느림, 테스트 실패 구분, roundtrip 미실행 표시) |
| triage | 건너뜀. 게이트를 꺼서 불리지 않음 |
| documenter | 보충 칸 (형식·결정 기록 기준). 노트 앱 동기화 안 함 (`vault_prefix` 비움) |
| discuss | 보충 칸 (묻지 않을 축, 늘 물을 네 가지) |
| spec | 보충 칸 (진입점, 테스트 데이터, 단위 테스트 기반 수용조건). `docs.e2e_guide` 비움 |
| planner | 보충 칸 (모듈 자리, 본보기, prefix_rules 등록), MCP context7 |
| plan-checker | 수정 금지에 `기획서.md`, `LICENSE` 추가. 보충 없음 |
| verifier | `dod_checks` 2개 (`ThreadLocal.withInitial`, `removeprefix/suffix`, 주석 줄 제외), 보충 칸 (등록 지점) |
| tutor | `learning.doc_domains`, `source_root`, `small_samples`, `docs.study_dir` = `docs/study`, MCP context7. 예제 저장소·캐시 비움 |

### 6단계: 확인

| 확인 | 결과 |
|---|---|
| `HC_OK` | 2 (게이트 끔) |
| 빈칸 / 빌드 빈칸 | 없음 / 없음 |
| 시나리오 태그 | 해당 없음 (게이트 끔) |
| `project.has_ui` | true |
| `domains_for.py --self-check` | 통과 |
| `dod_check.py` | 기존 소스 위반 0, 일부러 만든 위반 2건 모두 잡음 |
| 빌드 | exit 0, 27초 |
| 게이트 | exit 0, SKIP (`gate_disabled`) |

### 7단계

- 프로젝트 루트 `CLAUDE.md` 새로 만듦 (하네스 안내 절만)

### 비운 것

`e2e.*`, `docs.e2e_guide`, `docs.vault_prefix`, `learning.sample_repos`, `learning.cache_dir`, `learning.source_globs`, `project.app_id`, triage 보충, 6개 도메인 문서, format 추가 함정
