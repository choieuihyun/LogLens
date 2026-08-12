package io.loglens.core

import java.nio.charset.StandardCharsets
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class TruncatorTest {

    @Test fun `짧으면 그대로`() = assertEquals("abc", Truncator.truncate("abc", 100))

    @Test
    fun `ASCII 는 한도 안에서 잘리고 표시가 붙는다`() {
        val cut = Truncator.truncate("a".repeat(500), 100)!!
        assertTrue(Truncator.utf8Length(cut) <= 100)
        assertTrue(cut.endsWith(Truncator.MARK))
    }

    // 한글은 UTF-8 에서 3바이트입니다. 바이트 위치로 그냥 자르면 글자가 반으로 갈립니다.
    @Test
    fun `한글은 여러 한도에서 안 깨진다`() {
        val ko = "한글로그메시지".repeat(200)
        for (max in 20..200 step 7) {
            val c = Truncator.truncate(ko, max)!!
            assertTrue(Truncator.utf8Length(c) <= max, "max=$max 한도 초과")

            val body = c.removeSuffix(Truncator.MARK)
            assertTrue(ko.startsWith(body), "max=$max 원문의 앞부분이 아니다")

            val back = String(c.toByteArray(StandardCharsets.UTF_8), StandardCharsets.UTF_8)
            assertEquals(c, back, "max=$max UTF-8 왕복에서 깨졌다")
            assertFalse(c.contains('�'), "max=$max 깨진 글자가 있다")
        }
    }

    // 이모지는 4바이트, 자바에서는 char 두 개(서로게이트 페어)입니다.
    @Test
    fun `이모지는 반으로 갈리지 않는다`() {
        val emoji = "👍".repeat(100)
        for (max in 20..120 step 3) {
            val c = Truncator.truncate(emoji, max)!!
            assertTrue(Truncator.utf8Length(c) <= max, "max=$max 한도 초과")

            val body = c.removeSuffix(Truncator.MARK)
            var lone = false
            var i = 0
            while (i < body.length) {
                val ch = body[i]
                if (ch.isHighSurrogate()) {
                    if (i + 1 >= body.length || !body[i + 1].isLowSurrogate()) lone = true
                    i++
                } else if (ch.isLowSurrogate()) lone = true
                i++
            }
            assertFalse(lone, "max=$max 서로게이트 페어가 쪼개졌다")
        }
    }

    @Test fun `표시보다 작은 한도에서도 안 터진다`() = assertNotNull(Truncator.truncate("긴문자열입니다", 3))
    @Test fun `잘렸는지 판별`() = assertTrue(Truncator.isTruncated("x" + Truncator.MARK))
    @Test fun `null 은 null`() = assertEquals(null, Truncator.truncate(null))
}
