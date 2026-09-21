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
        LogLens.init(false)
        LogLens.addSink(sink)
    }

    @AfterTest
    fun tearDown() = LogLens.clearSinks()

    @Test
    fun `릴리스에서는 V 와 D 가 안 나가고 I 만 나간다`() {
        LogLens.v(D.AUTH, "TRACE")
        LogLens.d(D.AUTH, "DEBUG")
        LogLens.i(D.AUTH, "LOGIN_OK", "uid", 1)
        assertEquals(1, sink.size)
    }

    @Test
    fun `디버그에서는 V 와 D 도 나간다`() {
        LogLens.init(true)
        LogLens.v(D.AUTH, "TRACE")
        LogLens.d(D.AUTH, "DEBUG")
        assertEquals(2, sink.size)
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

    // ── 런타임으로 특정 도메인만 켜기 ──────────────────────────────────────
    // 릴리스에서 V/D 는 막히지만, 현장에서 "채팅만 상세 로그 보내주세요" 같은 요청이
    // 옵니다. 앱을 다시 빌드하지 않고 켜려면 출력 대상이 스스로 판단할 수 있어야 합니다.
    // logcat 쪽은 이걸 Log.isLoggable 로 구현해서 setprop 한 줄로 열립니다.

    /** 특정 태그만 강제로 통과시키는 가짜 출력 대상 */
    private class ForcingSink(private val openTag: String) : Sink {
        val got = mutableListOf<String>()
        override fun isForcedOn(level: Level, tag: String) = tag == openTag
        override fun write(level: Level, tag: String, body: String) {
            got += "$tag|$body"
        }
    }

    @Test
    fun `릴리스에서도 런타임으로 켠 도메인은 통과한다`() {
        val forcing = ForcingSink(openTag = "APP_AUTH")
        LogLens.clearSinks()
        LogLens.init(false)          // 릴리스
        LogLens.addSink(forcing)

        LogLens.d(D.AUTH, "OPENED")       // 켜 둔 도메인 → 통과해야 함
        LogLens.d(D.FILE_XFER, "BLOCKED") // 안 켠 도메인 → 막혀야 함

        assertEquals(1, forcing.got.size, forcing.got.toString())
        assertTrue(forcing.got[0].startsWith("APP_AUTH|evt=OPENED"), forcing.got[0])
    }

    @Test
    fun `런타임으로 켜지 않으면 릴리스에서 V 와 D 는 그대로 막힌다`() {
        LogLens.clearSinks()
        LogLens.init(false)
        LogLens.addSink(sink)         // isForcedOn 기본값 false

        LogLens.v(D.AUTH, "TRACE")
        LogLens.d(D.AUTH, "DEBUG")
        assertEquals(0, sink.size)
    }

    @Test
    fun `켜 두지 않아도 I 이상은 항상 나간다`() {
        val forcing = ForcingSink(openTag = "없는태그")
        LogLens.clearSinks()
        LogLens.init(false)
        LogLens.addSink(forcing)

        LogLens.i(D.AUTH, "ALWAYS")
        assertEquals(1, forcing.got.size)
    }
}
