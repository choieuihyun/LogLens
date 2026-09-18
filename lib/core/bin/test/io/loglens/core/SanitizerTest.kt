package io.loglens.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class SanitizerTest {

    @Test fun `공백은 언더스코어로`() = assertEquals("a_b", Sanitizer.value("a b"))
    @Test fun `줄바꿈은 두 글자 이스케이프로`() = assertEquals("a\\nb", Sanitizer.value("a\nb"))
    @Test fun `캐리지리턴과 탭도`() = assertEquals("a\\rb\\tc", Sanitizer.value("a\rb\tc"))
    @Test fun `파이프는 슬래시로`() = assertEquals("a/b", Sanitizer.value("a|b"))
    @Test fun `null 은 빈 값 표시로`() = assertEquals("-", Sanitizer.value(null))
    @Test fun `빈 문자열도 빈 값 표시로`() = assertEquals("-", Sanitizer.value(""))
    @Test fun `공백뿐이어도 빈 값 표시로`() = assertEquals("-", Sanitizer.value("   "))
    @Test fun `한글은 그대로`() = assertEquals("로그인성공", Sanitizer.value("로그인성공"))
    @Test fun `숫자 타입도 처리`() = assertEquals("42", Sanitizer.value(42))

    @Test
    fun `정리된 값에는 공백도 파이프도 줄바꿈도 없다`() {
        val v = Sanitizer.value("a b\nc|d\te")
        assertFalse(v.contains(" "))
        assertFalse(v.contains("|"))
        assertFalse(v.contains("\n"))
    }

    @Test fun `메시지는 공백을 살린다`() = assertEquals("로그인 성공", Sanitizer.message("로그인 성공"))
    @Test fun `메시지도 줄바꿈은 처리한다`() = assertEquals("a\\nb", Sanitizer.message("a\nb"))
    @Test fun `메시지는 파이프를 살린다`() = assertEquals("a | b", Sanitizer.message("a | b"))
    @Test fun `빈 메시지는 null`() = assertNull(Sanitizer.message("   "))

    @Test
    fun `유효한 키`() {
        assertTrue(Sanitizer.isValidKey("uid"))
        assertTrue(Sanitizer.isValidKey("_x"))
        assertTrue(Sanitizer.isValidKey("flowId2"))
    }

    @Test
    fun `유효하지 않은 키`() {
        assertFalse(Sanitizer.isValidKey("2x"), "숫자로 시작")
        assertFalse(Sanitizer.isValidKey("a b"), "공백 포함")
        assertFalse(Sanitizer.isValidKey("사용자"), "한글")
        assertFalse(Sanitizer.isValidKey(""), "빈 문자열")
        assertFalse(Sanitizer.isValidKey(null), "null")
    }
}
