package io.loglens.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class MaskerTest {

    private val m = Masker()

    @Test fun `token 은 가린다`() = assertEquals("***", m.apply("token", "eyJhbGciOi"))
    @Test fun `password 는 가린다`() = assertEquals("***", m.apply("password", "hunter2"))
    @Test fun `대소문자는 상관없다`() = assertEquals("***", m.apply("PassWord", "hunter2"))

    // 이 세 개가 이 클래스의 존재 이유입니다.
    // 키 이름이 일부만 맞아도 가리면 멀쩡한 필드까지 사라집니다.
    @Test fun `authType 은 가리지 않는다`() = assertEquals("oauth2", m.apply("authType", "oauth2"))
    @Test fun `tokenCount 도 가리지 않는다`() = assertEquals("3", m.apply("tokenCount", "3"))
    @Test fun `emailVerified 도 가리지 않는다`() = assertEquals("true", m.apply("emailVerified", "true"))
    @Test fun `일반 키는 통과`() = assertEquals("123", m.apply("uid", "123"))

    @Test fun `키를 추가할 수 있다`() = assertTrue(m.plus("deviceSerial").isSensitive("deviceserial"))
    @Test fun `추가해도 기본 목록은 유지된다`() = assertTrue(m.plus("deviceSerial").isSensitive("token"))
    @Test fun `가린 값도 공백 없는 한 덩어리`() = assertFalse(Masker.MASK.contains(" "))

    @Test
    fun `직접 고른 목록으로 만들 수 있다`() {
        val only = Masker.of(setOf("secretCode"))
        assertTrue(only.isSensitive("secretcode"))
        assertFalse(only.isSensitive("token"), "기본 목록을 쓰지 않는다")
    }
}
