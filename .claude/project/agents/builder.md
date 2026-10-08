# builder 보충 (2026-09-30, /setup)

## 우선순위와 당부
- 첫 gradle 빌드는 데몬 기동과 의존성 다운로드 때문에 오래 걸린다. 느린 것은 실패가 아니다
- 빌드 명령은 컴파일 사이에 뷰어 단위 테스트(`unittest`)를 돌린다. 출력에 `FAIL:` 또는 `ERROR:` 로 시작하는 테스트 블록이 있으면 컴파일 에러가 아니라 **테스트 실패**로 요약한다
- 빌드 명령에는 형식 대조(`make roundtrip`)가 들어 있지 않다. 바뀐 파일이 형식 계약(`parser.py`, `payloads.py`, `Formatter.kt`, `LineFormat.kt`, `Sanitizer.kt`, `Truncator.kt`, `Masker.kt`, `Payload.kt`, `tools/roundtrip/`)에 닿으면 보고에 "make roundtrip 미실행" 을 붙인다
