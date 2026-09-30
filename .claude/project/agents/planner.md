# planner 보충 (2026-09-30, /setup)

## 더 볼 곳
- 본보기
  - 뷰어 분석 모듈: `viewer/loglens/events.py` + `viewer/tests/test_events.py`, `viewer/loglens/flows.py` + `viewer/tests/test_flows.py`
  - HTTP 엔드포인트: `viewer/loglens/server.py` 의 기존 핸들러
  - 새 로그 소스: `viewer/loglens/sources/base.py` 의 `LogSource` 를 구현 (`filesrc.py` 참고)
- 컨벤션: `docs/CONVENTIONS.md`

## 우선순위와 당부
- 뷰어의 새 기능은 `viewer/loglens/<이름>.py` 평평한 모듈과 `viewer/tests/test_<이름>.py` 로 둔다. 하위 폴더는 `sources/`, `web/` 뿐이다
- 새 모듈을 만들면 계획에 "`.claude/project.json` 의 `domains.prefix_rules` 에 `<이름>` 과 `test_<이름>` 등록" 을 적는다. 안 하면 그 변경이 ALL 로 떨어진다
- 새 config 키를 들이면 `viewer/config.schema.json` 과 `config.py` 를 함께 계획한다
