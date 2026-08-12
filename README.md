# LogLens

**도메인 기반 구조화 로깅 표준 + 전용 실시간 뷰어/분석기.**

로그 뷰어는 찍힌 로그만큼만 좋아진다. 그래서 진짜 레버리지는 뷰어가 아니라
**로그를 규격대로 찍게 만드는 쪽**에 있고, 뷰어는 그 규격을 착취하는 소비 도구다.

```
[앱] --구조화 로그--> [logcat 버퍼]
  (A) 로깅 라이브러리        │ adb
                             ▼
                   [ (B) 뷰어 / 분석기 ]
```

두 컴포넌트 사이에 **코드 의존이 없다.** 공유하는 건 한 줄짜리 레코드 규격뿐이다.

📄 **문서** — [동작 원리·아키텍처](docs/ARCHITECTURE.md) · [계약 전문](docs/RECORD_FORMAT.md) ·
[구현 결정 기록](docs/DECISIONS.md) · [설계 초안(기획서)](기획서.md) · [문서 안내](docs/README.md)

> 다이어그램까지 렌더한 HTML 판: `open docs/architecture.html`

---

## 30초 만에 보기

기기도, adb 도, 파이썬 패키지 설치도 필요 없다.

```bash
make viewer     # 합성 로그로 뷰어 실행 → http://127.0.0.1:8420
```

진짜 emitter 가 도는 걸 보려면:

```bash
make demo       # Java 라이브러리 → 파일 → 뷰어  (end-to-end)
make emit       # 계약이 어떻게 생겼는지 stdout 으로
make test       # 전부 검증 (뷰어 + 라이브러리 + 왕복)
```

---

## 레코드 규격 (계약)

```
<레벨>/<PREFIX>_<도메인>: evt=<이벤트> key=value key=value | <자유 메시지>
```

```
2026-08-12 11:41:24.931 I/APP_AUTH: evt=LOGIN_OK flowId=f9254 uid=668 | 로그인 성공
2026-08-12 11:41:24.937 E/APP_NET: evt=REQUEST_FAIL host=api.example.test code=500 err=ConnectException:Failed_to_connect...
2026-08-12 11:41:24.930 I/APP_AUTH: evt=TOKEN_ISSUE flowId=f9254 token=*** expiresIn=3600 authType=oauth2
```

마지막 줄을 보라. `token` 은 가려졌고 `authType` 은 안 가려졌다.
마스킹이 [정확 키 매칭](docs/RECORD_FORMAT.md)이어야 하는 이유다 —
부분 일치로 가리면 `auth` 가 `authType` 까지 먹어치우고, 그러면 개발자가
마스킹을 우회하기 시작한다. 그게 진짜 사고로 이어진다.

**불변식**
- 태그 = `<PREFIX>_<DOMAIN>` → 도메인이 곧 logcat 태그 → `adb logcat -s APP_AUTH:*` 가 그대로 도메인 필터
- 한 줄 = 한 레코드 (여러 줄 분할 금지). 4KB 근처에서 **코드포인트 경계**로 자르고 `...[cut]`
- 값에는 공백·`|`·개행이 없다 (emitter 가 정화)
- 파서는 절대 예외를 던지지 않는다. 규격 위반은 강등이지 실패가 아니다

---

## (A) 로깅 라이브러리

```java
// 앱 부트스트랩 한 줄
LogLensAndroid.install(this);

// call site
LogLens.i(AppDomain.AUTH, "LOGIN_OK", "uid", uid, "msg", "로그인 성공");
LogLens.e(AppDomain.NET, "SOCKET_FAIL", e, "host", host);
LogLens.d(AppDomain.CHAT, "ROOM_ENTER");
```

### 도메인은 **앱이 공급한다**

이게 "어느 프로젝트에나 붙는다"의 전부다. 도메인 목록은 프로젝트의 정체성이라
라이브러리에 enum 으로 박는 순간 재사용이 끝난다.

```java
// 라이브러리: 도메인을 모른다
public interface LogDomain { String tag(); }

// 앱: 자기 도메인을 정의한다
public enum AppDomain implements LogDomain {
    AUTH, CHAT, NET, FILE_XFER;
    public String tag() { return "APP_" + name(); }
}
```

### 구조

| 모듈 | 내용 | 의존 |
|---|---|---|
| `lib/core` | `LogLens` 파사드, `Formatter`, `Sanitizer`, `Masker`, `Truncator`, `Sink`, `FileSink` | **없음** (순수 자바) |
| `lib/android` | `LogcatSink`, `LogLensAndroid` | Android |
| `lib/sample-domains` | `AppDomain` 예시 — 배포하지 않는다 | core |

core 가 안드로이드를 모르는 게 의도다. 덕분에 일반 JVM 에서 테스트되고,
**뷰어 파서와의 왕복 검증**을 실제로 돌릴 수 있다.

### 안 해도 되는 걱정
- **PII** — `token`/`password`/`ssn` 등은 emitter 가 키 이름으로 마스킹한다. call site 는 신경 쓰지 않는다
- **릴리스에서 V/D** — `Level.enabled(isDebug)` 로 문자열 조립 전에 걸러진다. `init()` 전 기본값은 "디버그 아님"
- **긴 값** — 코드포인트 경계에서 잘리고 `...[cut]` 이 붙는다. 한글도 이모지도 안 깨진다
- **싱크 예외** — 삼킨다. 로깅이 앱을 죽이면 안 된다

---

## (B) 뷰어 / 분석기

### 브라우저는 USB 에 접근할 수 없다 → 로컬 브리지

```
[기기] --adb logcat--> [로컬 서버(파싱)] --SSE--> [브라우저 GUI]
```

Electron 없이, 파일 주입 없이 실시간 스트리밍 + 웹 GUI. 의존성 0 (파이썬 표준 라이브러리만).

### 기능

- **도메인 탭** — 원클릭 필터. 이관 전 레거시 태그도 정규식으로 같은 탭에 끌어온다
- **레벨/검색/정규식 필터**
- **대상 앱 pid 자동추적** — `--package` 를 주면 adb 소스가 pid 를 풀고, "이 앱만" 토글이 뜬다.
  앱이 재시작돼 pid 가 바뀌면 따라잡는다. 이슈를 클릭한 상태에서는 이 필터가 비활성화된다
  (ANR 은 앱이 아니라 `ActivityManager` 가 찍으므로, 걸러버리면 방금 누른 이슈가 사라진다)
- **이슈 트레이** — 크래시(예외 클래스별)/ANR/네이티브/구조화 에러를 자동 그룹핑 + 카운트. 클릭하면 그 이슈만 필터
- **분석 대시보드** — 성공률, 실패 사유 분포, 퍼널 이탈, 도메인/이벤트 빈도
  ← *구조화 로그라서 가능한 것. 범용 logcat 뷰어는 문자열밖에 못 보므로 원리상 못 한다*

### config 로 프로젝트에 맞춘다

탭도 이슈 규칙도 코드에 없다. [`config.json`](viewer/examples/sample-app.json)
([스키마](viewer/config.schema.json))으로 갈아끼운다.

```bash
loglens --source adb --package com.your.app --config your-app.json
loglens --source file --file dump.log --follow     # 저장된 로그 재생
loglens --source synth                             # 기기 없이 데모
```

### config 는 자동으로 만든다

이관을 시작하지 않은 프로젝트에 "도메인 목록을 적으라"고 하면 아무도 안 쓴다.
그래서 실제 로그에서 초안을 뽑는다.

```bash
loglens --source adb --package com.your.app --init your-app.json
```

기기의 최근 logcat 을 표본으로 읽어 **대상 앱 pid 가 찍은 태그만** 골라내고,
이름으로 군집화해 탭 초안을 만든다 (`Chats` 와 `ChatListFragment` 는 한 탭으로).
이미 이관된 도메인은 도메인 탭으로, 아직인 것은 `legacyTagPattern` 탭으로 들어간다.

> **태그 이름과 빈도만 읽는다.** 메시지 본문은 집계에도 산출물에도 쓰지 않는다
> (테스트로 강제).

전체 0→1 절차는 [아키텍처 문서 §9](docs/ARCHITECTURE.md) 참고.

### 소스 추상화

`adb` / `file` / `synth` 가 한 인터페이스 뒤에 있다. 기기 없이 전부 개발·테스트·데모할 수 있고,
adb 재연결(기기 sleep, USB 재연결) 로직은 adb 소스 안에 갇혀 있다.

---

## 이 도구가 요구하는 것 — 솔직하게

**차별점에 해당하는 기능은 로그가 규격을 지킬 때만 작동한다.** 이건 결함이 아니라
전제다(기획서 §1의 "garbage in, garbage out"). 다만 그 전제를 흐리지 않고 적어 둔다.

| 기능 | 필요 조건 | 통합 0줄로? |
|---|---|:--:|
| 레벨 · 검색 · 정규식 필터 | 없음 | ✅ |
| pid 필터, 도메인 탭 라우팅 | 없음 | ✅ |
| 크래시 · ANR · 네이티브 이슈 그룹핑 | 없음 — 시스템 로그를 파싱한다 | ✅ |
| 도메인 / 이벤트 빈도 | 구조화 레코드 | ❌ |
| **성공률** | 이벤트 이름을 `_OK` / `_FAIL` 로 통일 | ❌ |
| **실패 사유 분포** | 실패 레코드에 `reason=` 또는 `err=` | ❌ |
| **퍼널 이탈** | 흐름 전체에 `flowId=` + config 에 단계 정의 | ❌ |

위 세 줄은 통합 없이 되지만, 그건 Android Studio Logcat + 알파다.
아래 네 줄이 이 도구의 존재 이유이고, **전부 규칙에 의존한다.**

### 가치 곡선에는 무릎이 있다

초안은 "call site #1 부터 가치"라고 적었다. 실제로는 그보다 늦다 —
한 줄을 옮기면 색칠된 칩 하나를 얻을 뿐이다. 성공률은 성공·실패 이벤트가 **쌍으로**
있어야 뜨고, 퍼널은 흐름 **전체**에 `flowId` 가 박혀야 뜬다.

**실질적인 최소 단위는 call site 하나가 아니라 "한 흐름 전체"다.**
로그인이든 전송이든, 시작·분기·끝이 다 계측된 흐름 하나. 거기서 처음으로
범용 도구가 못 하는 화면이 나온다.

### 그래서 이건 무엇인가

지저분한 로그를 고쳐 주는 도구가 아니다. **규율을 지키면 그게 보상으로 돌아오게
만드는 도구다.** 규칙을 어긴 로그는 사라지지 않고 그냥 분석에서 빠진다(§강등 사다리) —
그 비대칭이 채택 유인이다.

같은 성질이 OpenTelemetry·Sentry·구조화 로깅 전반에 있다. 넣은 만큼 나온다.

> 이 의존을 줄이는 두 갈래 — 파서 쪽 필드 추출 규칙(통합 0줄로 대시보드를 켜되 취약),
> 그리고 codemod(이관 비용 자체를 제거) — 는
> [DECISIONS.md D20](docs/DECISIONS.md) 에 적어 두었다. 아직 구현하지 않았다.

---

## 왕복 검증 — 이 저장소에서 유일하게 중요한 테스트

손으로 쓴 픽스처는 **양쪽에 같은 오해를 심을 수 있다.** 내가 파서를 잘못 이해한 채로
픽스처를 쓰면 파서는 통과한다. 그래서 진짜 검사는 이것이다:

```
Java Formatter --생성--> 한 줄 --> Python Parser --> 필드 비교
```

```bash
make roundtrip
# roundtrip: 26 passed, 0 failed  (EXACT 22, TRUNC 4)
```

기대값은 Formatter 의 출력을 되읽어 만들지 않는다 — 입력으로부터 독립적으로 조립한다.
그래야 대조에 의미가 있다.

---

## 검증 상태

| | |
|---|---|
| 뷰어 (파서·집계·설정·자동생성) | 67 테스트 통과 |
| 라이브러리 core | 242 단언 통과 (javac 21) |
| 계약 왕복 | 26 케이스 통과 |
| `--source adb` + `--init` | **실기기로 검증** (연결·pid추적·스트리밍·config 자동생성) |
| `make demo` (emitter→파일→뷰어) | **실행 검증** |
| `lib/android` | **컴파일 검증** (android-36, source/target 8). 기기 실행은 아직 |
| gradle 빌드 | **미검증.** gradle 래퍼 부재 — 지금은 소스 복사/로컬 모듈로 붙인다 |
| 브라우저 렌더 | JS 문법·DOM 정합·API 모양은 테스트. **육안 확인은 아직** |

자세한 내용과 초안에서 바뀐 이유들 → [docs/DECISIONS.md](docs/DECISIONS.md)

---

## 문서

- [기획서.md](기획서.md) — 원래 설계 초안 (문제 정의, 설계 결정, 실전 교훈)
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 동작 원리 · 기술 스택 · 뷰어가 기기에 붙는 방식 · 0→1 절차**
- [docs/RECORD_FORMAT.md](docs/RECORD_FORMAT.md) — 계약 전문 (문법·불변식)
- [docs/DECISIONS.md](docs/DECISIONS.md) — 만들면서 초안과 달라진 것들

## 라이선스

MIT
