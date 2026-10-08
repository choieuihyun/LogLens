# 코딩 컨벤션

흩어져 있던 규칙을 한곳에 모았다. 이유와 사연은 링크한 결정 기록에 있다.
새 규칙을 만드는 문서가 아니다. 이미 코드가 지키고 있는 것만 적는다.

## 공통

- 주석, 문서, 커밋 메시지는 한국어로 쓴다. 코드 식별자는 영어로 쓴다
- 없는 아키텍처 패턴을 새로 들이지 않는다. 주변 코드를 따른다
- 형식 계약(`docs/RECORD_FORMAT.md`)을 바꾸면 Kotlin 과 Python 양쪽을 같은 변경에서 고치고 `make roundtrip` 으로 확인한다.
  두 언어에 따로 박힌 값: `Truncator.MARK` ↔ `parser.TRUNCATION_MARK`, `Truncator.DEFAULT_MAX_BYTES` ↔ `tools/roundtrip/verify.py` 의 `MAX_BYTES`,
  원문 예약 필드 이름과 이스케이프 규칙 (`Payload.kt` ↔ `viewer/loglens/payloads.py`)
- 요청·응답 본문을 통째로 남길 때는 `LogLens.payload` 를 쓴다. 일반 로그의 `msg` 나 필드에 본문을 넣지 않는다.
  로그인·토큰·인증 응답은 원문으로도 싣지 않는다 ([DECISIONS D25](DECISIONS.md))

## 뷰어 (Python, `viewer/`)

- **표준 라이브러리만 쓴다.** `pyproject.toml` 의 `dependencies = []` 를 유지한다 ([DECISIONS D13](DECISIONS.md#d13-뷰어는-표준-라이브러리만-쓴다))
- **Python 3.8 에서 돌아야 한다** (`requires-python = ">=3.8"`). 새 모듈은 `from __future__ import annotations` 로 시작하고,
  `match`, `str.removeprefix` 같은 3.9 이상 런타임 기능을 쓰지 않는다
- 테스트는 `unittest` 로 쓴다 (pytest 없음). `viewer/tests/test_<모듈>.py`
- 파서는 예외를 던지지 않는다. 실패는 강등한다 ([RECORD_FORMAT I3](RECORD_FORMAT.md))
- 근사값을 정확한 값인 척하지 않는다. 근사나 미관측이면 화면에 그렇다고 표시한다 (D11, D23-⑤).
  원문도 같다: 빠진 조각은 그 자리에 표시하고, 값을 바꿔 보여 주지 않는다 (JSON 의 큰 정수를 숫자로 읽지 않는다)
- 설정 규칙의 오타는 조용히 넘기지 않고 로딩 시점에 예외로 알린다 (D12)

## 라이브러리 (Kotlin, `lib/`)

- **minSdk 21, JVM 바이트코드 1.8.** 문법은 디슈가링되지만 런타임 API 는 안 된다. Android API 26 이상에만 있는 JDK API 를 쓰지 않는다 (D19)
- `:core` 는 안드로이드를 모른다. 안드로이드 전용 판단은 `Sink` 에 위임한다 (D22)
- 공개 로깅 API 는 두 벌을 유지한다: 자바용 `vararg kv: Any?` (`@JvmStatic`), Kotlin 전용 `vararg fields: Pair` (`@JvmSynthetic`), 그리고 인자 없는 오버로드 (D21)
- 안전한 방향으로 실패한다. 초기화 전에는 debug 가 꺼져 있고, 릴리스에서는 기본으로 아무것도 내보내지 않는다.
  릴리스 출력은 앱이 `ReleasePolicy` 로 직접 고를 때만 열린다. 새 출력 경로를 만들 때도 기본값은 "닫힘" 이다 (D8, D24)
- 원문(`payload`)은 어떤 정책에서도 릴리스에서 나가지 않는다. 받겠다고 밝힌 출력 대상(`Sink.acceptsPayload`)에만 보낸다 (D25)
- 수정은 `src/` 에서만 한다. `bin/` 은 IDE 가 만든 복사본이다

## 웹 화면 (`viewer/loglens/web/`)

- 자동화와 테스트가 찾는 요소에는 `id` 를 붙인다
- 로그에서 온 글자는 전부 `esc()` 를 거쳐 화면에 넣는다. 원문 본문은 앱 밖(서버)에서 온 문자열이다
- 트리를 누르면 그 자리에서 펼치고 접는다. 클릭에 다른 의미(필터 등)를 싣지 않는다 (D23-④)
