package io.loglens.core

import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class PayloadTest {

    private val f = Formatter(Masker(), Truncator.DEFAULT_MAX_BYTES, Formatter.Diagnostics.SILENT)

    @AfterTest
    fun tearDown() = LogLens.clearSinks()

    /** 뷰어가 하는 일을 흉내냅니다: `| ` 뒤를 떼어 되돌리고 순서대로 붙입니다. */
    private fun reassemble(lines: List<String>): String =
        lines.joinToString("") { line ->
            val at = line.indexOf(" | ")
            if (at < 0) "" else Payload.unescape(line.substring(at + 3))
        }

    private fun field(line: String, key: String): String? =
        Regex("""(?:^| )$key=(\S+)""").find(line.substringBefore(" | "))?.groupValues?.get(1)

    // ── 이스케이프 ──────────────────────────────────────────────────────────

    @Test
    fun `원래 있던 백슬래시 n 과 진짜 줄바꿈이 구분되어 돌아온다`() {
        val src = "{\"memo\":\"첫줄\\n둘째줄\"}\n다음 줄\t탭\r끝"
        val esc = Payload.escape(src)
        assertFalse(esc.contains('\n') || esc.contains('\r') || esc.contains('\t'), esc)
        assertEquals(src, Payload.unescape(esc))
    }

    @Test
    fun `조각 앞뒤 공백은 이스케이프되고 안쪽 공백과 파이프는 그대로다`() {
        val esc = Payload.escape(" a | b ")
        assertEquals("\\sa | b\\s", esc)
        assertEquals(" a | b ", Payload.unescape(esc))
    }

    @Test
    fun `스페이스가 아닌 공백도 가장자리에서는 살아남는다`() {
        val src = " 가운데　"
        val esc = Payload.escape(src)
        assertEquals(esc.trim(), esc, "파서가 떼어 낼 공백이 가장자리에 남으면 안 된다")
        assertEquals(src, Payload.unescape(esc))
    }

    @Test
    fun `줄을 가르는 글자와 제어문자는 유니코드 이스케이프로 간다`() {
        val src = "a b\u0085c\u0001d"
        val esc = Payload.escape(src)
        assertEquals("a\\u2028b\\u0085c\\u0001d", esc)
        assertEquals(src, Payload.unescape(esc))
    }

    @Test
    fun `우연히 잘림 표시로 끝나는 조각은 잘린 줄로 보이지 않게 바뀐다`() {
        val src = "말줄임...[cut]"
        val esc = Payload.escape(src)
        assertFalse(esc.endsWith(Truncator.MARK), esc)
        assertEquals(src, Payload.unescape(esc))
    }

    @Test
    fun `모르는 이스케이프는 그대로 둔다`() {
        assertEquals("\\q \\u12 \\", Payload.unescape("\\q \\u12 \\"))
    }

    // ── 나누기 ──────────────────────────────────────────────────────────────

    @Test
    fun `짧은 원문은 한 줄이고 그대로 돌아온다`() {
        val lines = f.payload("ADDR_ADD_RES_BODY", "{\"result\":\"ok\"}", arrayOf("flowId", "a1"), id = "t1")
        assertEquals(
            listOf("evt=ADDR_ADD_RES_BODY flowId=a1 plId=t1 plPart=1 plParts=1 plBytes=15 | {\"result\":\"ok\"}"),
            lines,
        )
    }

    @Test
    fun `큰 원문은 여러 줄로 나뉘고 어느 줄도 한도를 넘지 않는다`() {
        val src = buildString { repeat(900) { append("{\"이름\":\"홍길동$it\",\"이모지\":\"👍🏻\"},\n") } }
        val lines = f.payload("LIST_BODY", src, arrayOf("flowId", "f9"), id = "t2")

        assertTrue(lines.size > 5, "조각 수 ${lines.size}")
        for (line in lines) {
            assertTrue(Truncator.utf8Length(line) <= Truncator.DEFAULT_MAX_BYTES, "줄 길이 ${Truncator.utf8Length(line)}")
            assertFalse(line.endsWith(Truncator.MARK), "원문 줄에는 잘림 표시가 없다")
            assertFalse(line.contains('\n'), "한 줄 = 한 레코드")
            assertEquals("f9", field(line, "flowId"), "호출부 필드는 조각마다 반복된다")
            assertEquals("t2", field(line, "plId"))
            assertEquals(lines.size.toString(), field(line, "plParts"))
        }
        assertEquals((1..lines.size).map { it.toString() }, lines.map { field(it, "plPart") })
        assertEquals(src, reassemble(lines))
        assertEquals(Truncator.utf8Length(src).toString(), field(lines[0], "plBytes"))
    }

    @Test
    fun `좁은 한도에서도 한글과 이모지가 조각 경계에서 깨지지 않는다`() {
        val small = Formatter(Masker(), 120, Formatter.Diagnostics.SILENT)
        val src = "가나다라마바사👍🏻아자차카타파하 \\ 끝\n".repeat(7)
        for (extra in 0..6) {                 // 경계가 글자마다 한 번씩 걸리게 밀어 봅니다
            val text = "x".repeat(extra) + src
            val lines = small.payload("E", text, null, id = "t3")
            assertTrue(lines.size > 3)
            for (line in lines) assertTrue(Truncator.utf8Length(line) <= 120, "$extra: ${Truncator.utf8Length(line)}")
            assertEquals(text, reassemble(lines), "밀기 $extra")
        }
    }

    @Test
    fun `조각이 공백에서 갈려도 공백을 잃지 않는다`() {
        val small = Formatter(Masker(), 100, Formatter.Diagnostics.SILENT)
        val src = "a b c d e f g h i j k l m n o p q r s t u v w x y z ".repeat(6)
        val lines = small.payload("E", src, null, id = "t4")
        for (line in lines) assertEquals(line.trimEnd(), line, "줄 끝에 공백이 남으면 파서가 떼어 낸다")
        assertEquals(src, reassemble(lines))
    }

    @Test
    fun `빈 원문과 null 도 한 줄을 남긴다`() {
        assertEquals(listOf("evt=E plId=t5 plPart=1 plParts=1 plBytes=0"), f.payload("E", "", null, id = "t5"))
        assertEquals(listOf("evt=E plId=t6 plPart=1 plParts=1 plBytes=0"), f.payload("E", null, null, id = "t6"))
    }

    @Test
    fun `상한을 넘으면 뒤를 버리고 원래 크기를 알린다`() {
        val src = "가".repeat(1000)                       // 3000 바이트
        val lines = f.payload("E", src, null, maxTotalBytes = 1000, id = "t7")
        val got = reassemble(lines)
        assertEquals("가".repeat(333), got, "글자 중간에서 끊지 않는다")
        assertEquals("999", field(lines[0], "plBytes"))
        assertEquals("3000", field(lines[0], "plCut"))
    }

    @Test
    fun `상한 안이면 plCut 이 없다`() {
        val lines = f.payload("E", "짧다", null, id = "t8")
        assertEquals(null, field(lines[0], "plCut"))
    }

    // ── 함께 싣는 필드 ──────────────────────────────────────────────────────

    @Test
    fun `필드는 일반 로그와 같은 규칙으로 정리되고 가려진다`() {
        val lines = f.payload("E", "x", arrayOf("name", "내 문서", "token", "abc", "uid", null), id = "t9")
        assertEquals("evt=E name=내_문서 token=*** uid=- plId=t9 plPart=1 plParts=1 plBytes=1 | x", lines[0])
    }

    @Test
    fun `msg 와 예약 이름은 필드로 쓸 수 없다`() {
        val warned = mutableListOf<String>()
        val loud = Formatter(Masker(), Truncator.DEFAULT_MAX_BYTES) { warned += it }
        val lines = loud.payload("E", "x", arrayOf("msg", "끼어들기", "plId", "가짜", "place", "서울"), id = "t10")
        assertEquals("evt=E place=서울 plId=t10 plPart=1 plParts=1 plBytes=1 | x", lines[0])
        assertEquals(2, warned.size, warned.toString())
    }

    // ── 본문 안 민감 키 ─────────────────────────────────────────────────────

    private fun masked(text: String) = Payload.mask(text, Masker())

    @Test
    fun `JSON 의 민감 키는 값만 가려진다`() {
        assertEquals(
            """{"uid":7,"token":"***","name":"홍길동","pin":"***","authType":"oauth2"}""",
            masked("""{"uid":7,"token":"eyJhbGciOi.abc","name":"홍길동","pin":1234,"authType":"oauth2"}"""),
        )
    }

    @Test
    fun `민감 키의 값이 객체나 배열이면 통째로 가린다`() {
        assertEquals(
            """{"credentials":"***","ok":true,"cookie":"***"}""",
            masked("""{"credentials":{"id":"a","pw":"b}"},"ok":true,"cookie":["x","y"]}"""),
        )
    }

    @Test
    fun `따옴표가 이스케이프된 값도 끝까지 가린다`() {
        assertEquals("""{"password":"***","n":1}""", masked("""{"password":"a\"b,c","n":1}"""))
    }

    @Test
    fun `문자열 안에 한 번 더 싸인 JSON 도 가린다`() {
        assertEquals(
            """{"jsonData":"{\"name\":\"홍\",\"mobile\":\"***\",\"otp\":\"***\"}"}""",
            masked("""{"jsonData":"{\"name\":\"홍\",\"mobile\":\"010-1234-5678\",\"otp\":123456}"}"""),
        )
    }

    @Test
    fun `XML 요소와 속성과 CDATA 를 가린다`() {
        assertEquals(
            """<user id="7" email="***"><name>홍</name><ns:token>***</ns:token><phone>***</phone></user>""",
            masked("""<user id="7" email="a@b.c"><name>홍</name><ns:token>abc</ns:token><phone><![CDATA[010<1>]]></phone></user>"""),
        )
    }

    @Test
    fun `주소와 폼의 민감 키를 가린다`() {
        assertEquals("uid=7&token=***&q=a", masked("uid=7&token=abc.def&q=a"))
        assertEquals("""{"url":"http://h/p?access_token=***&x=1"}""", masked("""{"url":"http://h/p?access_token=zz&x=1"}"""))
    }

    @Test
    fun `이름이 일부만 겹치는 키는 가리지 않는다`() {
        val src = """{"tokenCount":3,"emailVerified":true,"authType":"x"}<tokens>3</tokens>"""
        assertEquals(src, masked(src))
    }

    @Test
    fun `닫히지 않은 민감 값은 끝까지 가린다`() {
        assertEquals("""{"a":1,"token":"***"""", masked("""{"a":1,"token":"abc 잘린"""))
    }

    @Test
    fun `아주 긴 문자열 값에서도 죽지 않는다`() {
        val big = "\\\"x".repeat(60_000)
        val src = """{"data":"$big","token":"t"}"""
        assertEquals("""{"data":"$big","token":"***"}""", masked(src))
    }

    @Test
    fun `가리기는 자르기보다 먼저 한다`() {
        // 먼저 자르면 닫는 따옴표가 사라져서 토큰 앞부분이 그대로 남는다
        val src = """{"token":"${"s".repeat(500)}","z":1}"""
        val lines = f.payload("E", src, null, maxTotalBytes = 100, id = "t11")
        assertFalse(reassemble(lines).contains("sss"), reassemble(lines))
    }

    // ── LogLens.payload ─────────────────────────────────────────────────────

    private enum class D : LogDomain {
        MEMBER;
        override fun tag() = "APP_$name"
    }

    @Test
    fun `디버그에서는 D 레벨로 나가고 두 벌의 API 가 같은 줄을 만든다`() {
        val sink = MemorySink()
        LogLens.init(true)
        LogLens.addSink(sink)

        LogLens.payload(D.MEMBER, "RES_BODY", "{\"a\":1}", "flowId" to "f1")     // Kotlin
        LogLens.payload(D.MEMBER, "RES_BODY", "{\"a\":1}", "flowId", "f1")        // Java 와 동일
        LogLens.payload(D.MEMBER, "RES_BODY", "{\"a\":1}")                        // 필드 없음

        val strip = { s: String -> s.replace(Regex(""" plId=\S+"""), "") }
        assertEquals(3, sink.size)
        assertEquals(strip(sink.bodies()[0]), strip(sink.bodies()[1]))
        assertEquals("evt=RES_BODY plPart=1 plParts=1 plBytes=7 | {\"a\":1}", strip(sink.bodies()[2]))
        assertTrue(sink.lines()[0].contains(" D/APP_MEMBER: "), sink.lines()[0])
        assertTrue(sink.bodies()[0] != sink.bodies()[1], "묶음 id 는 호출마다 다르다")
    }

    @Test
    fun `릴리스에서는 원문이 나가지 않는다`() {
        val sink = MemorySink()
        LogLens.init(false)
        LogLens.addSink(sink)
        LogLens.payload(D.MEMBER, "RES_BODY", "{\"a\":1}")
        assertEquals(0, sink.size)
    }

    @Test
    fun `받겠다고 밝히지 않은 출력 대상에는 원문이 가지 않는다`() {
        val plain = object : Sink {
            val got = mutableListOf<String>()
            override fun write(level: Level, tag: String, body: String) {
                got += body
            }
        }
        val accepting = MemorySink()
        LogLens.init(true)
        LogLens.addSink(plain)
        LogLens.addSink(accepting)

        LogLens.payload(D.MEMBER, "RES_BODY", "본문")
        LogLens.d(D.MEMBER, "SUMMARY")

        assertEquals(listOf("evt=SUMMARY"), plain.got, "일반 로그는 받고 원문은 안 받는다")
        assertEquals(2, accepting.size)
    }

    @Test
    fun `상한을 바꿀 수 있다`() {
        val sink = MemorySink()
        LogLens.init(true)
        LogLens.addSink(sink)
        try {
            LogLens.setPayloadMaxBytes(10)
            LogLens.payload(D.MEMBER, "RES_BODY", "0123456789abcdef")
            assertTrue(sink.lastBody()!!.contains("plBytes=10 plCut=16 | 0123456789"), sink.lastBody())
        } finally {
            LogLens.setPayloadMaxBytes(Payload.DEFAULT_MAX_TOTAL_BYTES)
        }
    }

    @Test
    fun `예약 이름 판별은 pl 뒤 대문자만이다`() {
        assertTrue(Payload.isReserved("plId"))
        assertTrue(Payload.isReserved("plAnything"))
        assertFalse(Payload.isReserved("place"))
        assertFalse(Payload.isReserved("platform"))
        assertFalse(Payload.isReserved("pl"))
    }
}
