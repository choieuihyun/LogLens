# verifier 보충 (2026-09-30, /setup)

## 더 볼 곳
새로 만든 것이 연결됐는지 볼 등록 지점:
- 새 HTTP 엔드포인트: `viewer/loglens/server.py` 의 `do_GET` / `do_POST` 라우트 분기, 그리고 그것을 부르는 `viewer/loglens/web/app.js`
- 새 로그 소스: `viewer/loglens/sources/__init__.py` 의 `build()` 와 `__all__`, `cli.py` 의 `--source` 선택지
- 새 config 키: `viewer/loglens/config.py`, `viewer/config.schema.json`, `viewer/examples/sample-app.json`
- 새 화면 요소: `viewer/loglens/web/index.html` 의 `id` 와 `app.js` 의 참조가 서로 맞는지
- 새 gradle 모듈: `lib/settings.gradle.kts` 의 `include`
- 새 뷰어 모듈: `.claude/project.json` 의 `domains.prefix_rules` 등록

## 우선순위와 당부
- 코드 판단의 기준은 `docs/CONVENTIONS.md`. 본보기는 `viewer/loglens/events.py` 와 `viewer/tests/test_events.py`
- 형식 계약 파일이 바뀌었는데 Kotlin 과 Python 중 한쪽만 바뀌었으면 연결 누락으로 올린다
