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
→ [계약 전문](docs/RECORD_FORMAT.md)

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

- **도메인 탭** — 원클릭 필터. 이관 전 레거시 태그도 정규식으로 같은 탭에 끌어온다 → call site #1 부터 점진 도입
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

### 소스 추상화

`adb` / `file` / `synth` 가 한 인터페이스 뒤에 있다. 기기 없이 전부 개발·테스트·데모할 수 있고,
adb 재연결(기기 sleep, USB 재연결) 로직은 adb 소스 안에 갇혀 있다.

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
| 뷰어 (파서·집계·설정) | 50 테스트 통과 (파서·집계·서버 API) |
| 라이브러리 core | 242 단언 통과 (javac 21) |
| 계약 왕복 | 26 케이스 통과 |
| `lib/android`, gradle 빌드 | **소스만.** Android SDK/gradle 부재로 미컴파일 |
| `--source adb` | **미검증.** 기기 부재. `file`/`synth` 경로로 대체 검증 |

자세한 내용과 초안에서 바뀐 이유들 → [docs/DECISIONS.md](docs/DECISIONS.md)

---

## 문서

- [기획서.md](기획서.md) — 원래 설계 초안 (문제 정의, 설계 결정, 실전 교훈)
- [docs/RECORD_FORMAT.md](docs/RECORD_FORMAT.md) — 계약 전문
- [docs/DECISIONS.md](docs/DECISIONS.md) — 만들면서 초안과 달라진 것들

## 라이선스

MIT
