# spec 보충 (2026-09-30, /setup)

## 더 볼 곳
- 진입점: `make viewer` (= `cd viewer && python3 -m loglens --source synth --config examples/sample-app.json`), 주소 `http://127.0.0.1:8420/` (`--port` 로 바꿈)
- 인증 없음. 로그인 전제를 적지 않는다
- 테스트 데이터
  - 합성 소스 `viewer/loglens/sources/synthetic.py` (기기 없이 전 기능 시연)
  - 소스별 실제 모양 샘플 `viewer/tests/fixtures/*.log`
  - `make demo`: 진짜 Kotlin 라이브러리가 파일에 쓰고 뷰어가 따라 읽는 전 구간
- 여러 세션: 같은 뷰어에 브라우저 탭 여러 개를 붙여 SSE 전파를 볼 수 있다

## 우선순위와 당부
- 런타임 게이트와 E2E 가 없다. 수용조건은 가능하면 **단위 테스트로 확인할 수 있게** 쓰고, 확인할 테스트 파일(`viewer/tests/test_<모듈>.py`, `lib/core/src/test/...`)을 적는다
- 화면으로만 확인되는 조건(렌더, 배치)은 `verify_manual` 로 돌린다. 웹 UI 는 브라우저 렌더를 자동 검증하지 않는다 (DECISIONS 「검증되지 않은 것」)
- 형식 계약에 닿는 조건은 `make roundtrip` 통과를 조건에 넣는다
