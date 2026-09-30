# format

<!--
이 문서는 에이전트가 이 도메인을 작업하기 전에 읽는 지식이다.
explorer, planner, implementer, verifier, discuss, spec, triage 가 읽고, documenter 가 코드 변경에 맞춰 갱신한다.
처음 내용은 /setup 이 사용자와 대화해서 채운다.

쓰는 규칙:
- 코드에서 grep 으로 확인할 수 있는 이름(파일, 클래스, 함수, 엔드포인트)으로 적는다. 에이전트가 이 이름으로 찾아간다
- 코드가 이미 말해 주는 것(함수 시그니처, 필드 목록)은 옮겨 적지 않는다. 코드에 없는 것을 적는다: 왜, 무엇을 지켜야, 어디서 터졌나
- 모르는 절은 비워 둔다. 추측으로 채우면 에이전트가 그 추측을 사실로 쓴다
- 문서와 코드가 다르면 코드가 맞다. 에이전트는 차이를 "도메인 문서 낡음" 으로 보고한다
-->

최종 수정: 2026-09-30

## 한 줄 요약

Kotlin 라이브러리(emitter)가 찍는 로그 한 줄과 Python 뷰어(parser)가 읽는 한 줄이 같은 모양이라는 계약.
두 컴포넌트는 코드 의존이 없고 이 형식으로만 묶인다. 문법 전문은 [docs/RECORD_FORMAT.md](../../RECORD_FORMAT.md).

## 용어

| 용어 | 뜻 | 코드에서의 이름 |
|---|---|---|
| body | `evt=<EVENT> k=v ... \| msg` 부분. 양쪽이 공유하는 유일한 계약 | `Formatter.body()`, `parser._BODY` |
| 접두사 | 소스마다 다른 앞부분 (threadtime / brief / 파일 싱크). 계약 아님 | `parser._PREFIX_PATTERNS`, `LineFormat.render()` |
| 강등 | 파싱 실패 시 예외 대신 한 단계 낮은 종류로 떨어뜨림: structured → unstructured → raw | `STRUCTURED`, `UNSTRUCTURED`, `RAW` |
| 센티널 | 빈 값/`null` 대신 쓰는 `-` | `Sanitizer` |
| 잘림 표시 | 한도를 넘어 잘린 줄 끝에 붙는 `...[cut]` | `Truncator.MARK`, `parser.TRUNCATION_MARK` |
| 왕복 검증 | Kotlin 이 만든 줄을 Python 이 되읽어 대조 | `tools/roundtrip/`, `make roundtrip` |

## 불변식 (깨지면 안 되는 것)

- 한 줄 = 한 레코드. 값과 메시지 양쪽에서 `\n` `\r` `\t` 는 리터럴 이스케이프 (RECORD_FORMAT I1, I5)
- 파서는 예외를 던지지 않는다. 실패는 `RAW` 강등. `raw` 필드는 항상 원문으로 채운다 (I3)
- emitter 는 엄격하다. 파서가 봐주는 것(줄 끝 공백 등)이라도 emitter 는 만들면 안 된다 (I3)
- 잘림은 UTF-8 바이트로 세고 코드포인트 경계에서 끊는다 (I2, DECISIONS D5)
- 마스킹은 소문자 정확 키 매칭. `contains` 부분일치 금지 (I6)
- `PREFIX` 는 config 값이므로 정규식에 넣기 전에 `re.escape` (DECISIONS D3)
- 두 언어에 같은 값이 따로 박혀 있다. 한쪽만 바꾸면 안 된다:
  `Truncator.MARK` ↔ `parser.TRUNCATION_MARK`, `Truncator.DEFAULT_MAX_BYTES` ↔ `tools/roundtrip/verify.py` 의 `MAX_BYTES`

## 위험 지점

위험 축 이름은 고정이다 (SYNC, EVENT, THREAD, DB, LIST). 이 도메인에서 해당하는 곳만 적는다.

| 축 | 이 도메인에서 어디 | 왜 위험한가 |
|---|---|---|
| SYNC | Kotlin `Formatter`/`Sanitizer`/`Truncator` ↔ Python `parser.py` | 같은 계약이 두 언어에 따로 구현돼 있다. 한쪽만 고치면 단위 테스트는 양쪽 다 초록인데 실제 줄이 강등된다 |
| THREAD | `LineFormat` 의 날짜 포맷 `ThreadLocal` | `SimpleDateFormat` 은 스레드 안전하지 않다. `ThreadLocal.withInitial()` 은 Android API 26+ 라 minSdk 21 에서 죽는다 (D19) |

## 핵심 모듈

| 파일 또는 모듈 | 역할 |
|---|---|
| `lib/core/src/main/kotlin/io/loglens/core/Formatter.kt` | body 조립 (필드, 예외 요약, 잘림) |
| `lib/core/src/main/kotlin/io/loglens/core/LineFormat.kt` | 파일 싱크 접두사(연도 포함 타임스탬프) |
| `lib/core/.../Sanitizer.kt`, `Masker.kt`, `Truncator.kt` | 값 정리, 민감 키 마스킹, 코드포인트 경계 잘림 (emitter 도메인이지만 계약에 직접 영향) |
| `viewer/loglens/parser.py` | 접두사 3종 + 공용 body 파서, 강등 사다리 |
| `tools/roundtrip/` (`RoundTrip.kt`, `verify.py`) | 양쪽 대조. 이 계약을 증명하는 유일한 검사 |
| `viewer/tests/fixtures/*.log` | 소스별 실제 모양 샘플 (threadtime, brief, filesink) |
| `docs/RECORD_FORMAT.md` | 계약 전문 |

## 흔한 함정

- **줄 끝 공백 한 칸으로 레코드 전체가 강등됐다.** 합성 생성기가 필드 뒤에 공백을 남겨 `UPLOAD_DONE` 이 전부 unstructured 가 됐고, FILE_XFER 성공률이 0% 로 나왔다. 로그는 멀쩡해 보이고 숫자만 틀리는 종류 (D7)
- **픽스처만으로는 계약을 증명 못 한다.** 손으로 쓴 픽스처는 양쪽에 같은 오해를 심는다. 형식을 건드리면 `make roundtrip` 을 돌린다. 하네스 빌드 명령에는 roundtrip 이 들어 있지 않다
- **logcat 은 연도를 안 찍는다.** 접두사 정규식에 연도를 요구하면 adb 소스가 전부 raw 로 떨어진다. adb 는 `-v threadtime` 으로 고정 (D1)
- **도메인 문자 집합은 `[A-Z0-9_]+`.** `[A-Z]+` 로 좁히면 `FILE_XFER`, `API2` 가 거부된다 (D2)
- **Java 8 API ≠ Android 가 주는 Java 8 API.** core 에서 새 JDK API 를 쓰면 minSdk 21 기기에서 로딩 시점에 죽는다 (D19)

## 외부 의존

- `adb logcat` 의 출력 형식 (threadtime, brief). 테스트는 `viewer/tests/fixtures/` 로 대신한다

## 시나리오

<!-- 이 도메인의 E2E 시나리오 위치와 태그. 게이트가 이 태그로 재생한다 -->

런타임 게이트를 꺼 두었다 (E2E 없음). 대신:

- 태그: `format`
- 위치: `viewer/tests/test_parser.py`, `lib/core/src/test/kotlin/io/loglens/core/FormatterTest.kt`, `make roundtrip`

## 변경 이력

| 날짜 | 변경 내용 | 관련 파일 |
|---|---|---|
| 2026-09-30 | /setup 으로 첫 작성 (RECORD_FORMAT, DECISIONS 에서 추림) | |
