# templates

새 프로젝트에 하네스를 얹을 때 복사되는 뼈대.

| 파일 | 용도 |
|---|---|
| `project.json.tmpl` | 도메인 목록, 명령 빈칸, 금지 글롭 등 프로젝트마다 채우는 값 |
| `CLAUDE.md.tmpl` | 대상 프로젝트 CLAUDE.md 끝에 `/setup` 이 덧붙이는 하네스 안내 절 |
| `DOMAIN.md.tmpl` | 도메인 문서 뼈대. `/setup` 이 대화로 채우고 documenter 가 갱신한다 |
| `choices.md` | 세팅할 때 사용자에게 보여 줄 선택지 (프로젝트 유형, 테스트 도구, 아키텍처, 공유 상태 경로 등). core 에서 걷어 낸 스택 전용 규칙도 여기 있다 |

이 폴더는 설치할 때 대상의 `.claude/templates/` 로 통째로 복사되고 `/setup` 이 읽는다.
`project.json.tmpl` 만은 대상의 `.claude/project.json` 으로도 복사된다 (이미 있으면 덮지 않는다).
`core/scripts/harness_config.py` 가 이 경로를 찾는다.

## project.json 키

json 에는 주석을 못 쓰므로 설명은 여기 둔다.

| 키 | 뜻 | 안 채우면 |
|---|---|---|
| `project.name` | 사람이 읽는 이름. 로그 표시용 | 표시만 비어 보인다 |
| `project.has_ui` | 사용자가 보는 화면이 있는가. `false` 면 UI 식별자 매핑, UI 식별자 검증, 화면 갱신 전략 같은 화면 전용 항목이 "해당 없음" 이 된다 | `null` 은 "모름" 이고 화면이 있는 것으로 본다. 화면 전용 검사를 조용히 끄지 않기 위해서다 |
| `project.app_id` | 설치/실행 대상 식별자 (앱 패키지, 서비스 이름 등) | 어댑터 명령에서 이 값을 쓰면 빈칸이 남아 실행 전에 막힌다 |
| `project_root` | 저장소 루트 절대경로. 비우면 `.claude` 의 상위로 잡는다 | 자동 산출 |
| `adapter` | `adapters/<이름>.json` 의 파일명 | 런타임 게이트가 명령을 몰라 exit 3 |
| `adapter_inline` | 어댑터 파일 대신 project.json 안에 직접 적는 어댑터 객체. 있으면 `adapter` 보다 먼저 쓴다. 어댑터 파일을 따로 만들 만큼 공유할 일이 없는 프로젝트에 쓴다. 시나리오가 아직 없는 프로젝트는 `runtime_gate: false` 와 함께 `{"name": ..., "build": "<빌드 또는 테스트 명령>"}` 만 적어도 된다 | `adapter` 를 쓴다 |
| `adapter_override` | 어댑터 파일 위에 일부만 덮어쓸 값. 예: `{"logs": {"command": "docker compose logs --tail=200"}}`, `{"e2e": {"dir_default": "tests/e2e"}}`. 객체는 키 단위로 합친다 | 어댑터 파일 그대로 |
| `runtime_gate` | 런타임 게이트를 쓸지. E2E 개념이 없는 프로젝트는 `false` | `true` 로 보고 어댑터를 요구한다 |
| `vars` | 어댑터 명령의 빈칸을 채우는 값. 어댑터가 요구하는 것만 넣는다 (예: 안드로이드 어댑터의 `{BUILD_TASK}`, `{INSTALL_TASK}`). 템플릿은 비어 있고, 무엇이 필요한지는 로더가 빈칸 목록으로 알려 준다 | 빈칸이 남으면 게이트가 실행 전에 멈춘다 |
| `env` | 게이트 실행 전에 export 할 환경변수 | 생략 |
| `env_candidates` | 기기마다 경로가 다른 환경변수의 후보 목록. 존재하는 첫 경로를 쓴다 | 생략 |
| `worktree_markers` | 이 파일이 있어야 올바른 워크트리로 인정한다. 비면 어댑터의 `detect` 를 쓴다 | 어댑터 값 |
| `e2e.dir` | E2E 시나리오 디렉토리 (저장소 상대경로) | 어댑터 기본값 |
| `e2e.tag_key` | 태그를 yaml 목록으로 적는 스택(maestro 등)에서 그 키 이름. 어댑터의 `tag_scan.key` 를 덮어쓴다. 정규식으로 태그를 읽는 스택(playwright 등)에서는 쓰이지 않는다 | 어댑터 기본값을 쓴다 |
| `domains.dir_rules` | 폴더 이름이 곧 도메인인 규칙 | 모든 변경이 ALL(전체 회귀) |
| `domains.prefix_rules` | 파일명 접두사가 도메인을 가리키는 규칙 | 위와 같음 |
| `dod_checks` | 화면/모듈 완료 기준 중 기계로 확정되는 항목. `{id, applies_to, require\|forbid, message}` 목록. `core/scripts/dod_check.py` 가 돌린다 | 기계 검증을 못 했다고 보고한다 (통과가 아니다) |
| `forbidden_globs` | 에이전트가 절대 못 고치는 파일 패턴 | 금지 없음 |
| `risk_axes` | 위험 축별 글롭. `{"SYNC": [...], "EVENT": [...], "THREAD": [...], "DB": [...], "LIST": [...]}`. 걸리면 explorer 가 그 축을 무조건 올린다. 축 이름은 이 다섯 개로 고정이다 | 축 판정이 매번 explorer 재량이 된다 |
| `risk_globs` | 건드리면 파급이 큰 공유 파일 패턴. explorer 가 위험 신호로 올린다 | 위험 가중 없음 |
| `ui_test_id` | UI 자동화가 요소를 찾는 식별자 속성 이름 (testTag, testID, data-testid 등) | 셀렉터 규칙 검증을 건너뛴다 |
| `docs.conventions` | 그 프로젝트의 코딩 컨벤션 문서 | 컨벤션 검증을 건너뛴다 |
| `docs.e2e_guide` | E2E 시나리오 작성 가이드 문서 (인증 통과 방법 포함) | spec 이 인증 전제를 주석으로만 남기고, 확정 못 한 수용조건은 verify_manual 로 돌린다. 자동 재생되는 시나리오가 줄어든다 |
| `docs.domain_map` | 도메인 문서 루트 | documenter 가 도메인 문서를 갱신하지 않는다 |
| `docs.study_dir` | 학습 노트를 쌓는 디렉토리 | `/study` 가 파일을 남기지 않는다 |
| `docs.vault_prefix` | 외부 노트 앱으로 동기화할 때 붙는 경로 접두사 | 동기화를 건너뛴다 |
| `learning.cache_dir` | 공식 샘플 저장소를 얕은 클론으로 받아 둘 로컬 캐시 경로 | tutor 가 샘플 근거 없이 문서만 본다 |
| `learning.sample_repos` | 공식 샘플 저장소 URL 목록. 1순위 근거 | 위와 같음 |
| `learning.doc_domains` | 공식 문서 도메인 목록. WebSearch 를 여기로 제한한다 | 검색 제한 없이 돌아 블로그가 섞인다 |
| `learning.source_root` | 이 저장소의 실제 사용처를 grep 할 루트 | 대조를 못 해 학습이 문서 요약이 된다 |
| `learning.small_samples` | 학습 표본으로 쓸 작은 파일 목록 | 대형 파일이 표본으로 뽑힐 수 있다 |
| `learning.source_globs` | 샘플 저장소에서 받아 둘 소스 파일 글롭 (예: `**/*.kt`, `**/*.tsx`, `**/*.go`). 희소 체크아웃에 쓴다 | 문서(.md)만 받는다. 샘플 코드 근거가 없다 |
| `crash_provider` | 크래시 인테이크 바인딩. `kind` 가 `none` 이면 `/fix --crash` 는 미설정이라고 말하고 멈춘다 | `none` |

## 왜 빈칸을 코드가 아니라 여기에 두나

`core/` 는 대상 프로젝트로 그대로 복사된다. 값이 코드 안에 박혀 있으면
복사할 때마다 코드를 고쳐야 하고, 고친 코드는 원본과 갈라져 되돌아오지 못한다.
빈칸이 json 한 곳에 모여 있으면 복사한 뒤 채우기만 하면 된다.
