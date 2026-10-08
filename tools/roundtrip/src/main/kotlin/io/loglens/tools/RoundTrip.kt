package io.loglens.tools

import io.loglens.core.Formatter
import io.loglens.core.Level
import io.loglens.core.LineFormat
import io.loglens.core.LogDomain
import io.loglens.core.Masker
import io.loglens.core.Payload
import io.loglens.core.Sanitizer
import io.loglens.core.Truncator
import java.io.FileDescriptor
import java.io.FileOutputStream
import java.io.PrintStream

/**
 * 대조 검증용 로그 생성기 — 양쪽이 정말 같은 형식을 쓰는지 확인합니다.
 *
 * 직접 손으로 쓴 테스트 데이터에는 **같은 오해가 양쪽에 들어갈 수 있습니다.**
 * 제가 파서를 잘못 이해한 채로 데이터를 만들면 파서는 통과합니다. 그래서 진짜 검증은 이겁니다:
 *
 * ```
 * Kotlin Formatter --만든다--> 한 줄 --> Python 파서 --> 필드 비교
 * ```
 *
 * 케이스마다 세 줄을 표준 출력으로 냅니다 (탭 구분):
 * ```
 * CASE   <이름>   <모드: EXACT|TRUNC>
 * CANON  <domain>|<event>|<k=v,k=v>|<msg>
 * LINE   <완성된 한 줄>
 * ```
 * `tools/roundtrip/verify.py` 가 이걸 받아 파싱하고 CANON 과 대조합니다.
 *
 * 원문(PAYLOAD) 케이스는 LINE 이 여러 줄입니다. 뷰어가 조각을 모아 되살린 본문이
 * 입력과 같은지 봅니다. 본문에는 줄바꿈이 들어 있을 수 있어서 CANON 에는 16진수로 싣습니다:
 * ```
 * CASE   <이름>   PAYLOAD
 * CANON  <domain>|<event>|<k=v,k=v>|<기대 본문의 UTF-8 16진수>|<plCut 또는 빈칸>
 * LINE   <조각 1>
 * LINE   <조각 2> ...
 * ```
 *
 * CANON 은 Formatter 의 출력을 되읽어서 만들지 않고 **입력값에서 따로 계산합니다.**
 * 그래야 비교에 의미가 있습니다.
 */

private enum class D : LogDomain {
    AUTH, CHAT, NET, FILE_XFER, API2;
    override fun tag() = "APP_$name"
}

private val F = Formatter(Masker(), Truncator.DEFAULT_MAX_BYTES, Formatter.Diagnostics.SILENT)
private val M = Masker()
private lateinit var out: PrintStream

fun main() {
    out = PrintStream(FileOutputStream(FileDescriptor.out), true, "UTF-8")

    emit("평범한 레코드", Level.I, D.AUTH, "LOGIN_OK", null, "uid", 123, "msg", "로그인 성공")
    emit("이벤트만", Level.D, D.CHAT, "ROOM_ENTER", null)
    emit("필드만", Level.E, D.NET, "SOCKET_FAIL", null, "host", "10.0.0.1", "code", 500)
    emit("메시지만", Level.I, D.CHAT, "MSG_SEND", null, "msg", "그냥 메시지")
    emit("도메인에 언더스코어", Level.I, D.FILE_XFER, "UPLOAD_DONE", null, "size", 1048576)
    emit("도메인에 숫자", Level.I, D.API2, "CALL_OK", null, "code", 200)

    emit("빈 값", Level.I, D.NET, "X", null, "a", null, "b", "", "c", "   ")
    emit("값 속 공백", Level.I, D.FILE_XFER, "UPLOAD_DONE", null, "name", "내 문서.pdf")
    emit("값 속 줄바꿈", Level.W, D.NET, "X", null, "dump", "line1\nline2")
    emit("값 속 파이프", Level.W, D.NET, "X", null, "expr", "a|b")
    emit("값 속 탭", Level.W, D.NET, "X", null, "t", "a\tb")
    emit("한글 값", Level.I, D.AUTH, "PROFILE", null, "name", "최의현")
    emit("이모지 값", Level.I, D.CHAT, "REACT", null, "emoji", "👍🏻")

    emit("마스킹", Level.W, D.AUTH, "TOKEN_REFRESH", null,
        "token", "eyJhbGciOiJIUzI1NiJ9.abc", "uid", 7)
    emit("과하게 가리지 않음", Level.I, D.AUTH, "LOGIN_OK", null,
        "authType", "oauth2", "tokenCount", 3, "emailVerified", true)

    emit("메시지 속 파이프는 살아남는다", Level.I, D.NET, "X", null, "msg", "a | b | c")
    emit("메시지 속 등호", Level.I, D.NET, "X", null, "msg", "k=v 처럼 보이는 문장")
    emit("메시지 속 줄바꿈", Level.I, D.NET, "X", null, "msg", "첫줄\n둘째줄")
    emit("메시지가 evt= 로 시작", Level.I, D.NET, "X", null, "msg", "evt=FAKE")

    emit("예외", Level.E, D.CHAT, "SEND_FAIL", IllegalStateException("session closed"), "room", 3)
    emit("메시지 없는 예외", Level.E, D.NET, "BOOM", NullPointerException())

    emit("흐름을 잇는 ID", Level.I, D.AUTH, "LOGIN_START", null, "flowId", "f1001", "uid", 42)

    // Kotlin 전용 Pair API 로 만든 줄도 같은 형식이어야 합니다.
    emitPairs("Kotlin Pair API", Level.I, D.AUTH, "LOGIN_OK", "uid" to 123, "msg" to "로그인 성공")
    emitPairs("Kotlin Pair API + 마스킹", Level.W, D.AUTH, "TOKEN_REFRESH",
        "token" to "eyJhbGciOiJIUzI1NiJ9.abc", "authType" to "oauth2")

    // 잘림 — 필드 값이 통째로 날아가므로 정확히 대조할 수 없습니다.
    // 대신 "한 줄 유지 / 바이트 한도 / 파서가 안 죽음" 을 봅니다.
    emitTrunc("긴 ASCII", Level.V, D.NET, "TRACE", "payload", "a".repeat(8000))
    emitTrunc("긴 한글", Level.V, D.NET, "TRACE", "payload", "한글".repeat(4000))
    emitTrunc("긴 이모지", Level.V, D.NET, "TRACE", "payload", "👍".repeat(3000))
    emitTrunc("긴 메시지", Level.V, D.NET, "TRACE", "msg", "긴 메시지 ".repeat(2000))

    // ── 원문: 잘리지 않고 여러 줄로 나뉘어, 뷰어에서 글자 하나 안 틀리고 돌아와야 합니다 ──
    emitPayload("원문: 짧은 JSON", D.NET, "RES_BODY", "{\"result\":\"ok\"}", null, null, "flowId", "f1")
    emitPayload("원문: 필드 없음", D.NET, "RES_BODY", "<a b=\"1\">텍스트</a>")
    emitPayload("원문: 빈 본문", D.NET, "RES_BODY", "")
    emitPayload("원문: 원래 있던 백슬래시 n 과 진짜 줄바꿈", D.NET, "RES_BODY",
        "{\"memo\":\"첫줄\\n둘째줄\",\"path\":\"C:\\\\dir\"}\n  들여쓴\t줄\r\n끝")
    emitPayload("원문: 앞뒤 공백과 파이프", D.NET, "RES_BODY", "  앞 | 가운데 | 뒤 \u00A0")
    emitPayload("원문: 줄을 가르는 글자와 제어문자", D.NET, "RES_BODY", "a\u2028b\u2029c\u0085d\u0001e\u000Bf")
    emitPayload("원문: 잘림 표시로 끝나는 본문", D.NET, "RES_BODY", "말줄임...[cut]")
    emitPayload("원문: evt= 로 시작하는 본문", D.NET, "RES_BODY", "evt=FAKE k=v | 가짜")
    emitPayload("원문: 한글과 이모지 여러 조각", D.NET, "LIST_BODY",
        (1..700).joinToString(",\n") { "{\"이름\":\"홍길동$it\",\"반응\":\"👍🏻\",\"메모\":\"a \\\\ b\"}" },
        null, null, "flowId", "f2", "name", "내 문서")
    // 조각 경계가 글자마다 한 번씩 걸리게 길이를 조금씩 바꿉니다. 한 줄에 딱 맞는 경우도 이 안에 있습니다.
    for (n in 3660..3760 step 4) {
        emitPayload("원문: 한 줄 경계 $n", D.NET, "EDGE_BODY", "가".repeat(40) + "x".repeat(n - 120) + " 끝")
    }
    for (n in 0..5) {
        emitPayload("원문: 공백에서 갈림 $n", D.NET, "EDGE_BODY", "y".repeat(n) + "ab ".repeat(2600))
    }
    emitPayload("원문: 본문 안 민감 키", D.AUTH, "PROFILE_BODY",
        "{\"uid\":7,\"token\":\"eyJhbGciOi.abc\",\"mobile\":\"010-1234-5678\",\"authType\":\"oauth2\"}",
        "{\"uid\":7,\"token\":\"***\",\"mobile\":\"***\",\"authType\":\"oauth2\"}", null,
        "token", "필드의 토큰도 가려진다")
    emitPayload("원문: 상한을 넘으면 뒤를 버린다", D.NET, "HUGE_BODY",
        "가".repeat(30_000), "가".repeat(Payload.DEFAULT_MAX_TOTAL_BYTES / 3), 90_000)
}

/**
 * 원문 케이스. 기대 본문은 **입력에서** 정합니다 — 가려지거나 잘리는 경우만 따로 적습니다.
 */
private fun emitPayload(
    name: String, domain: D, event: String, text: String,
    expected: String? = null, expectedCut: Int? = null, vararg kv: Any?,
) {
    val want = expected ?: text
    val hex = want.toByteArray(Charsets.UTF_8).joinToString("") { "%02x".format(it) }
    out.println("CASE\t$name\tPAYLOAD")
    out.println("CANON\t${canon(domain, event, null, kv).substringBeforeLast('|')}|$hex|${expectedCut ?: ""}")
    for (body in F.payload(event, text, kv)) {
        out.println("LINE\t${LineFormat.render(Level.D, domain.tag(), body)}")
    }
}

private fun emit(name: String, lv: Level, domain: D, event: String, t: Throwable?, vararg kv: Any?) {
    val body = F.body(event, kv, t)
    val mode = if (Truncator.isTruncated(body)) "TRUNC" else "EXACT"
    out.println("CASE\t$name\t$mode")
    out.println("CANON\t${canon(domain, event, t, kv)}")
    out.println("LINE\t${LineFormat.render(lv, domain.tag(), body)}")
}

/** Kotlin 전용 Pair API 로 같은 줄이 나오는지도 대조합니다. */
private fun emitPairs(
    name: String, lv: Level, domain: D, event: String, vararg fields: Pair<String, Any?>,
) {
    val flat = fields.flatMap { listOf(it.first, it.second) }.toTypedArray()
    emit(name, lv, domain, event, null, *flat)
}

private fun emitTrunc(name: String, lv: Level, domain: D, event: String, vararg kv: Any?) {
    val body = F.body(event, kv, null)
    out.println("CASE\t$name\tTRUNC")
    out.println("CANON\t${domain.name}|${Sanitizer.event(event)}||")
    out.println("LINE\t${LineFormat.render(lv, domain.tag(), body)}")
}

/**
 * 기대값을 **입력값에서** 따로 계산합니다.
 * Formatter 의 출력을 되읽지 않는 게 핵심입니다 — 그러면 자기 자신과 비교하는 꼴이 됩니다.
 */
private fun canon(domain: D, event: String, t: Throwable?, kv: Array<out Any?>): String {
    val fields = LinkedHashMap<String, String>()
    var msg: String? = null

    val pairs = (kv.size / 2) * 2
    var i = 0
    while (i < pairs) {
        val k = kv[i]?.toString()
        if (!Sanitizer.isValidKey(k)) { i += 2; continue }
        if (k == Formatter.MSG_KEY) { msg = kv[i + 1]?.toString(); i += 2; continue }
        fields[k!!] = M.apply(k, Sanitizer.value(kv[i + 1]))
        i += 2
    }
    if (t != null) {
        fields["err"] = Sanitizer.value(Formatter.describe(t))
        Formatter.topFrame(t)?.let { fields["at"] = Sanitizer.value(it) }
    }

    val parts = fields.entries.joinToString(",") { "${it.key}=${it.value}" }
    return "${domain.name}|${Sanitizer.event(event)}|$parts|${Sanitizer.message(msg) ?: ""}"
}
