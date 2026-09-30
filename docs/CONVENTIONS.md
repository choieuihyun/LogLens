# 코딩 컨벤션

흩어져 있던 규칙을 한곳에 모았다. 이유와 사연은 링크한 결정 기록에 있다.
새 규칙을 만드는 문서가 아니다. 이미 코드가 지키고 있는 것만 적는다.

## 공통

- 주석, 문서, 커밋 메시지는 한국어로 쓴다. 코드 식별자는 영어로 쓴다
- 없는 아키텍처 패턴을 새로 들이지 않는다. 주변 코드를 따른다
- 형식 계약(`docs/RECORD_FORMAT.md`)을 바꾸면 Kotlin 과 Python 양쪽을 같은 변경에서 고치고 `make roundtrip` 으로 확인한다.
  두 언어에 따로 박힌 값: `Truncator.MARK` ↔ `parser.TRUNCATION_MARK`, `Truncator.DEFAULT_MAX_BYTES` ↔ `tools/roundtrip/verify.py` 의 `MAX_BYTES`

## 뷰어 (Python, `viewer/`)

- **표준 라이브러리만 쓴다.** `pyproject.toml` 의 `dependencies = []` 를 유지한다 ([DECISIONS D13](DECISIONS.md#d13-뷰어는-표준-라이브러리만-쓴다))
- **Python 3.8 에서 돌아야 한다** (`requires-python = ">=3.8"`). 새 모듈은 `from __future__ import annotations` 로 시작하고,
  `match`, `str.removeprefix` 같은 3.9 이상 런타임 기능을 쓰지 않는다
- 테스트는 `unittest` 로 쓴다 (pytest 없음). `viewer/tests/test_<모듈>.py`
- 파서는 예외를 던지지 않는다. 실패는 강등한다 ([RECORD_FORMAT I3](RECORD_FORMAT.md))
- 근사값을 정확한 값인 척하지 않는다. 근사나 미관측이면 화면에 그렇다고 표시한다 (D11, D23-⑤)
- 설정 규칙의 오타는 조용히 넘기지 않고 로딩 시점에 예외로 알린다 (D12)

## 라이브러리 (Kotlin, `lib/`)

- **minSdk 21, JVM 바이트코드 1.8.** 문법은 디슈가링되지만 런타임 API 는 안 된다. Android API 26 이상에만 있는 JDK API 를 쓰지 않는다 (D19)
- `:core` 는 안드로이드를 모른다. 안드로이드 전용 판단은 `Sink` 에 위임한다 (D22)
- 공개 로깅 API 는 두 벌을 유지한다: 자바용 `vararg kv: Any?` (`@JvmStatic`), Kotlin 전용 `vararg fields: Pair` (`@JvmSynthetic`), 그리고 인자 없는 오버로드 (D21)
- 안전한 방향으로 실패한다. 초기화 전에는 debug 가 꺼져 있고, 출력 대상은 게이팅을 위로만 넘을 수 있다 (D8, D22)
- 수정은 `src/` 에서만 한다. `bin/` 은 IDE 가 만든 복사본이다

## 웹 화면 (`viewer/loglens/web/`)

- 자동화와 테스트가 찾는 요소에는 `id` 를 붙인다
- 트리를 누르면 그 자리에서 펼치고 접는다. 클릭에 다른 의미(필터 등)를 싣지 않는다 (D23-④)
