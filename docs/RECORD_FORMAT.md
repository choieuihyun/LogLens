# LogLens 레코드 포맷 — 계약 (v1)

라이브러리(emitter)와 뷰어(parser)를 잇는 **유일한 결합점**이다.
양쪽은 코드 의존이 없다. 이 문서와 `viewer/tests/fixtures/` 가 공동의 진실이다.

---

## 1. 레코드 본문 (body)

```
evt=<EVENT> <key>=<value> <key>=<value> | <free message>
```

- `evt=` 로 시작해야 구조화 레코드로 인정된다. 아니면 **unstructured** 로 강등(버려지지 않음).
- `key=value` 는 공백으로 구분. **값에는 공백·`|`·개행이 없다** (emitter 가 sanitize 책임).
- `| ` 뒤는 자유 메시지. 공백 허용. 없어도 된다.
- 필드가 없어도 되고(`evt=PING`), 메시지만 있어도 된다(`evt=PING | hello`).

### 문법 (EBNF 유사)

```
body    = "evt=" event , { " " , field } , [ " | " , message ] ;
event   = TOKEN ;
field   = key , "=" , value ;
key     = ( ALPHA | "_" ) , { ALNUM | "_" } ;
value   = TOKEN ;                     (* 공백/파이프/개행 불가, 1자 이상 *)
message = { ANY-EXCEPT-NEWLINE } ;
TOKEN   = 1*( any char except SPACE, TAB, CR, LF, "|" ) ;
```

---

## 2. 태그 = `<PREFIX>_<DOMAIN>`

```
APP_AUTH   APP_NET   APP_FILE_XFER
```

- `PREFIX` 는 프로젝트가 정한다 (`config.json` 의 `prefix`, 기본 `APP`).
- `DOMAIN` 은 **`[A-Z0-9_]+`**. 대문자·숫자·언더스코어.
  > 초안의 `[A-Z]+` 는 `FILE_XFER` / `API2` 같은 흔한 도메인을 거부한다. 넓혔다.
- 뷰어는 `PREFIX` 를 **정규식 이스케이프한 뒤** 패턴에 끼운다.

---

## 3. 줄 접두사 (prefix) — 소스마다 다르다

**초안의 단일 정규식은 틀렸다.** `\d{4}-\d\d-\d\d` 는 연도를 포함하는데, `adb logcat` 의
표준 포맷들은 연도를 찍지 않는다. 그래서 **얇은 접두사 파서 3종 + 공용 body 파서 1개** 구조로 간다.

| 소스 | 예시 | 비고 |
|---|---|---|
| `logcat -v threadtime` | `08-12 11:23:45.678  1234  5678 I APP_AUTH: <body>` | **뷰어 기본**. adb 호출 시 명시적으로 고정 |
| `logcat -v brief` | `I/APP_AUTH( 1234): <body>` | 초안 예시가 이 형태 |
| 파일 싱크 | `2026-08-12 11:23:45.678 I/APP_AUTH: <body>` | 우리가 포맷을 소유하므로 연도 포함 |

접두사에서 뽑는 것: `ts`, `pid`, `tid`, `level`, `tag`. 나머지는 `body` 로 넘긴다.
어느 접두사에도 안 맞으면 → `RAW` 레코드 (원문 보존, 뷰어에 회색으로 표시).

### 레벨
`V D I W E` — 그리고 logcat 이 내는 `F`(fatal), `A`(assert) 도 파서는 받아준다(`E` 로 승격).

---

## 4. 불변식 (invariants)

### I1. 한 줄 = 한 레코드
개행으로 쪼개지 않는다. 스택트레이스는 `\n` → `\\n` 이스케이프해서 한 줄에 밀어넣거나
필드로 요약(`err=ConnectException:timeout`)한다.

### I2. 4KB 잘림은 **코드포인트 경계**에서
logcat 은 한 줄당 ~4000 바이트 근처에서 자른다. emitter 가 먼저 자르되,
**UTF-8 바이트로 세고 코드포인트 경계에서 끊는다.** 한글은 3바이트/자라서
순진하게 바이트로 자르면 깨진 문자(mojibake)가 나온다. 자른 뒤 `...[cut]` 을 붙인다.

### I3. 파서는 관용적, emitter 는 엄격
파서는 절대 예외를 던지지 않는다.
잘린 줄(필드가 토큰 중간에 끊김, `|` 꼬리 없음)도 들어온다.
파싱 실패 = 예외가 아니라 **`RAW` 로 강등**.

파서가 봐주는 것 (emitter 는 그래도 만들면 안 되는 것):

| 입력 | 파서 동작 | 이유 |
|---|---|---|
| 줄 끝 공백 | `rstrip` 후 파싱 | 공백 한 칸에 레코드 전체를 강등시킬 이유가 없다. **실제로 이 한 칸에 당했다** — 합성 생성기가 필드 뒤에 공백을 남겨서 FILE_XFER 성공률이 0%로 나왔다 |
| `F`/`A` 레벨 | `E` 로 승격 | logcat 이 실제로 낸다 |
| 접두사 3종 혼재 | 각각 인식 | 소스마다 다르다 |

### I4. 빈 값 금지 → 센티널
`k=` 는 문법상 값이 0자라 토큰이 아니다. emitter 는 빈 문자열/`null` 을 **`-`** 로 쓴다.

| 입력 | 출력 |
|---|---|
| `null` | `k=-` |
| `""` | `k=-` |
| `"  "` | `k=-` |

### I5. sanitize 규칙
| 대상 | 제거/치환 |
|---|---|
| 키 | `[A-Za-z_][A-Za-z0-9_]*` 아니면 해당 쌍을 버리고 DEBUG 경고 |
| 값 | `\n` `\r` `\t` → `\n` `\r` `\t` (리터럴 2글자 이스케이프), 공백 → `_`, `\|` → `/` |
| 메시지 | `\n` `\r` `\t` → 리터럴 이스케이프. 공백·`\|` 는 허용 |

> 개행이 진짜 파서 킬러다. 공백보다 우선순위가 높다.

### I6. 마스킹은 **정확 키 매칭**
소문자로 정규화한 키가 민감 키 **집합에 속할 때만** 마스킹.
`contains` 부분일치 금지 — `auth` 가 `authType` 을 가리는 게 기획서 §9-2 의 교훈이다.
마스킹된 값도 여전히 공백 없는 토큰이어야 한다 → `***`.

기본 집합:
`password, passwd, pwd, token, access_token, refresh_token, id_token, jwt, secret,
 apikey, api_key, authorization, auth_header, cookie, session_id, ssn, rrn,
 phone, tel, mobile, email, mail, card, card_no, pin`

---

## 5. 정규식 (뷰어 구현 기준)

`PREFIX` 는 `re.escape` 적용 후 삽입.

```python
BODY = re.compile(
    r'^evt=(?P<event>[^\s|]+)'
    r'(?P<fields>(?:\s+[A-Za-z_][A-Za-z0-9_]*=[^\s|]+)*)'
    r'(?:\s+\|\s?(?P<msg>.*))?$'
)
TAG  = re.compile(r'^' + re.escape(prefix) + r'_(?P<domain>[A-Z0-9_]+)$')
```

접두사 3종은 `viewer/loglens/parser.py` 의 `_PREFIX_PATTERNS` 참조.

---

## 6. 정규화된 레코드 (파서 출력)

```jsonc
{
  "kind":   "structured" | "unstructured" | "raw",
  "ts":     "08-12 11:23:45.678",   // 소스가 준 그대로, 없으면 null
  "level":  "I",
  "tag":    "APP_AUTH",
  "domain": "AUTH",                 // structured 만
  "event":  "LOGIN_OK",             // structured 만
  "fields": { "uid": "123" },
  "msg":    "로그인 성공",
  "pid":    1234,
  "tid":    5678,
  "raw":    "<원문 한 줄>"
}
```

`raw` 는 항상 채운다. 뷰어가 어떤 레코드든 원문을 보여줄 수 있어야 한다.

---

## 7. 왕복 검증 (round-trip)

손으로 쓴 픽스처는 양쪽에 같은 실수를 심을 수 있다. 그래서 진짜 검증은:

```
Java Formatter --생성--> 한 줄 --> Python Parser --> 필드 비교
```

`lib/core` 의 `Formatter` 가 뽑은 줄을 `viewer` 파서가 되읽어 필드가 일치하는지 본다.
`make roundtrip` 참조.
