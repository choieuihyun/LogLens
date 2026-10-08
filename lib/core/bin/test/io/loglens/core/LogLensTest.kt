package io.loglens.core

import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class LogLensTest {

    private enum class D : LogDomain {
        AUTH, FILE_XFER;
        override fun tag() = "APP_$name"
    }

    private val sink = MemorySink()

    @BeforeTest
    fun setUp() {
        LogLens.clearSinks()
        LogLens.init(true)       // 형식을 보는 테스트는 줄이 나가야 한다. 릴리스 동작은 아래에서 따로 본다
        LogLens.addSink(sink)
    }

    @AfterTest
    fun tearDown() = LogLens.clearSinks()

    @Test
    fun `릴리스에서는 어떤 레벨도 나가지 않는다`() {
        LogLens.init(false)
        LogLens.v(D.AUTH, "TRACE")
        LogLens.d(D.AUTH, "DEBUG")
        LogLens.i(D.AUTH, "LOGIN_OK", "uid", 1)
        LogLens.w(D.AUTH, "SLOW")
        LogLens.e(D.AUTH, "BOOM", IllegalStateException("nope"), "uid" to 7)
        assertEquals(0, sink.size, sink.bodies().toString())
    }

    @Test
    fun `디버그에서는 모든 레벨이 나간다`() {
        LogLens.v(D.AUTH, "TRACE")
        LogLens.d(D.AUTH, "DEBUG")
        LogLens.i(D.AUTH, "LOGIN_OK", "uid", 1)
        LogLens.w(D.AUTH, "SLOW")
        LogLens.e(D.AUTH, "BOOM")
        assertEquals(5, sink.size)
    }

    @Test
    fun `태그가 곧 도메인이고 본문에는 태그가 없다`() {
        LogLens.i(D.FILE_XFER, "UPLOAD_DONE", "size", 10, "name", "a.png")
        val line = sink.lines()[0]
        assertTrue(line.contains(" I/APP_FILE_XFER: "), line)
        assertFalse(sink.lastBody()!!.contains("APP_FILE_XFER"), "태그를 본문에 넣지 않는다")
        assertTrue(
            line.matches(
                Regex("""^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} I/APP_FILE_XFER: evt=.*""")
            ),
            line,
        )
    }

    @Test
    fun `출력 대상이 예외를 던져도 앱은 안 죽고 다른 대상은 살아있다`() {
        LogLens.addSink(object : Sink {
            override fun write(level: Level, tag: String, body: String) = error("출력 대상 폭발")
        })
        LogLens.i(D.AUTH, "STILL_FINE")
        assertEquals(1, sink.size)
    }

    // ── 두 벌의 API 가 같은 결과를 낸다 ─────────────────────────────────────

    @Test
    fun `Kotlin 의 Pair 방식과 Java 의 가변 인자 방식이 같은 줄을 만든다`() {
        LogLens.i(D.AUTH, "LOGIN_OK", "uid" to 1, "msg" to "성공")   // Kotlin 전용
        val fromPairs = sink.lastBody()

        sink.clear()
        LogLens.i(D.AUTH, "LOGIN_OK", "uid", 1, "msg", "성공")        // Java 와 동일
        val fromVarargs = sink.lastBody()

        assertEquals(fromVarargs, fromPairs)
        assertEquals("evt=LOGIN_OK uid=1 | 성공", fromPairs)
    }

    @Test
    fun `필드가 없을 때도 애매하지 않게 처리된다`() {
        LogLens.i(D.AUTH, "NO_FIELDS")
        assertEquals("evt=NO_FIELDS", sink.lastBody())
    }

    @Test
    fun `Pair 방식에도 예외를 함께 넘길 수 있다`() {
        LogLens.e(D.AUTH, "BOOM", IllegalStateException("nope"), "uid" to 7)
        val body = sink.lastBody()!!
        assertTrue(body.startsWith("evt=BOOM uid=7 err=IllegalStateException:nope"), body)
    }

    @Test
    fun `초기화 전 기본값은 디버그 아님`() {
        // init 을 부르기 전 상태를 흉내내기 위해 릴리스로 초기화합니다.
        LogLens.init(false)
        assertFalse(LogLens.isDebug())
    }

    // ── 릴리스 정책 ─────────────────────────────────────────────────────────
    // 기본은 "릴리스에서는 아무것도". 앱이 초기화할 때 직접 골라야만 열립니다.

    /** 특정 태그만 강제로 통과시키는 가짜 출력 대상 (logcat 의 setprop 을 흉내냅니다) */
    private class ForcingSink(private val openTag: String?) : Sink {
        val got = mutableListOf<String>()
        override fun isForcedOn(level: Level, tag: String) = openTag == null || tag == openTag
        override fun acceptsPayload() = true
        override fun write(level: Level, tag: String, body: String) {
            got += "${level.c}|$tag|$body"
        }
    }

    private fun release(policy: ReleasePolicy?, sink: Sink) {
        LogLens.clearSinks()
        if (policy == null) LogLens.init(false) else LogLens.init(false, policy)
        LogLens.addSink(sink)
    }

    @Test
    fun `기본 정책에서는 출력 대상이 강제로 켜도 아무것도 나가지 않는다`() {
        val forcing = ForcingSink(openTag = null)
        release(null, forcing)

        LogLens.d(D.AUTH, "OPENED")
        LogLens.i(D.AUTH, "ALWAYS")
        LogLens.e(D.FILE_XFER, "BOOM")

        assertEquals(0, forcing.got.size, forcing.got.toString())
        assertTrue(LogLens.releasePolicy().isSilent())
    }

    @Test
    fun `레벨을 연 정책에서는 그 레벨부터 나간다`() {
        val forcing = ForcingSink(openTag = null)
        release(ReleasePolicy.WARN_AND_ABOVE, forcing)

        LogLens.d(D.AUTH, "DEBUG")
        LogLens.i(D.AUTH, "INFO")
        LogLens.w(D.AUTH, "WARN")
        LogLens.e(D.AUTH, "ERROR")

        assertEquals(listOf("W|APP_AUTH|evt=WARN", "E|APP_AUTH|evt=ERROR"), forcing.got,
            "스위치를 허용하지 않았으므로 출력 대상이 켜 달라고 해도 D, I 는 안 나간다")
    }

    @Test
    fun `런타임 스위치를 허용하면 켜 둔 도메인만 열린다`() {
        val forcing = ForcingSink(openTag = "APP_AUTH")
        release(ReleasePolicy.SILENT.withRuntimeSwitch(), forcing)

        LogLens.d(D.AUTH, "OPENED")       // 켜 둔 도메인 → 통과
        LogLens.d(D.FILE_XFER, "BLOCKED") // 안 켠 도메인 → 막힘
        LogLens.e(D.FILE_XFER, "BLOCKED_TOO")

        assertEquals(listOf("D|APP_AUTH|evt=OPENED"), forcing.got)
    }

    @Test
    fun `init 을 다시 부르면 정책은 기본값으로 돌아간다`() {
        val forcing = ForcingSink(openTag = null)
        release(ReleasePolicy.INFO_AND_ABOVE.withRuntimeSwitch(), forcing)
        LogLens.init(false)
        LogLens.e(D.AUTH, "BOOM")
        assertEquals(0, forcing.got.size)
    }

    @Test
    fun `출력 대상이 물음에 예외로 답해도 앱은 안 죽는다`() {
        val exploding = object : Sink {
            override fun isForcedOn(level: Level, tag: String): Boolean = error("스위치 확인 폭발")
            override fun acceptsPayload(): Boolean = error("원문 확인 폭발")
            override fun write(level: Level, tag: String, body: String) = error("여기까지 오면 안 된다")
        }
        val ok = ForcingSink(openTag = null)

        LogLens.clearSinks()
        LogLens.init(false, ReleasePolicy.SILENT.withRuntimeSwitch())
        LogLens.addSink(exploding)
        LogLens.addSink(ok)
        LogLens.d(D.AUTH, "SWITCHED")                 // isForcedOn 이 터져도 다른 출력 대상은 받는다

        LogLens.init(true)
        LogLens.payload(D.AUTH, "RES_BODY", "본문")   // acceptsPayload 가 터져도 마찬가지

        assertEquals(listOf("D|APP_AUTH|evt=SWITCHED"), ok.got.take(1))
        assertEquals(2, ok.got.size, ok.got.toString())
    }

    @Test
    fun `원문은 어떤 정책에서도 릴리스에서 나가지 않는다`() {
        val forcing = ForcingSink(openTag = null)
        release(ReleasePolicy.INFO_AND_ABOVE.withRuntimeSwitch(), forcing)

        LogLens.payload(D.AUTH, "RES_BODY", "{\"a\":1}")
        LogLens.i(D.AUTH, "SUMMARY")

        assertEquals(listOf("I|APP_AUTH|evt=SUMMARY"), forcing.got, "요약 로그는 나가도 원문은 안 나간다")
    }
}
