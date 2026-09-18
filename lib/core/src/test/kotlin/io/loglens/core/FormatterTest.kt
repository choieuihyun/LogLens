package io.loglens.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

class FormatterTest {

    private val f = Formatter()

    @Test fun `이벤트만`() = assertEquals("evt=ROOM_ENTER", f.body("ROOM_ENTER"))

    @Test
    fun `필드 하나`() =
        assertEquals("evt=LOGIN_OK uid=123", f.body("LOGIN_OK", arrayOf("uid", 123)))

    @Test
    fun `필드 순서가 유지된다`() =
        assertEquals("evt=X a=1 b=2 c=3", f.body("X", arrayOf("a", 1, "b", 2, "c", 3)))

    @Test
    fun `msg 키는 자유 메시지가 된다`() =
        assertEquals(
            "evt=LOGIN_OK uid=1 | 로그인 성공",
            f.body("LOGIN_OK", arrayOf("uid", 1, "msg", "로그인 성공")),
        )

    @Test
    fun `메시지만`() = assertEquals("evt=PING | 안녕", f.body("PING", arrayOf("msg", "안녕")))

    @Test
    fun `null 값은 빈 값 표시로`() = assertEquals("evt=X k=-", f.body("X", arrayOf("k", null)))

    @Test
    fun `값의 공백은 정리된다`() =
        assertEquals("evt=X name=a_b", f.body("X", arrayOf("name", "a b")))

    @Test
    fun `민감한 키는 가려진다`() =
        assertEquals(
            "evt=T token=*** authType=oauth2",
            f.body("T", arrayOf("token", "abc.def", "authType", "oauth2")),
        )

    // 가변 인자의 대가입니다. 컴파일 시점에 못 잡으니 개발 중에 시끄럽게 알립니다.
    // (Kotlin 호출부는 Pair 방식을 쓰면 이 실수 자체가 불가능합니다.)
    @Test
    fun `인자 개수가 홀수면 마지막을 버리고 경고한다`() {
        val warns = StringBuilder()
        val loud = Formatter(Masker(), Truncator.DEFAULT_MAX_BYTES) { warns.append(it) }
        assertEquals("evt=X a=1", loud.body("X", arrayOf("a", 1, "dangling")))
        assertTrue(warns.contains("홀수"))
    }

    @Test
    fun `잘못된 키는 건너뛰고 경고한다`() {
        val warns = StringBuilder()
        val loud = Formatter(Masker(), Truncator.DEFAULT_MAX_BYTES) { warns.append(it) }
        assertEquals("evt=X ok=1", loud.body("X", arrayOf("bad key", "v", "ok", 1)))
        assertTrue(warns.contains("잘못된 키"))
    }

    @Test
    fun `예외는 err 과 at 필드로 접힌다`() {
        val withEx = f.body("SEND_FAIL", arrayOf("room", 3), IllegalStateException("session closed"))
        assertTrue(withEx.contains("err=IllegalStateException:session_closed"), withEx)
        assertTrue(withEx.contains(" at="), withEx)
        assertFalse(withEx.contains("\n"), "한 줄이어야 한다")
    }

    @Test
    fun `예외 메시지가 길어도 잘라 담는다`() =
        assertTrue(f.body("X", null, RuntimeException("x".repeat(500))).length < 300)

    @Test
    fun `긴 본문은 잘리고 한 줄로 남는다`() {
        val long = f.body("X", arrayOf("msg", "한글".repeat(5000)))
        assertTrue(Truncator.isTruncated(long))
        assertTrue(Truncator.utf8Length(long) <= Truncator.DEFAULT_MAX_BYTES)
        assertFalse(long.contains("\n"))
    }

    // ── 필드 값 흔들림 방지 ────────────────────────────────────────────────
    // 필드 값이 자유 문자열이면 OPEN / open / Open 이 서로 다른 그룹이 되어
    // 집계가 조용히 쪼개진다. enum 을 넘기면 컴파일 시점에 막힌다.

    private enum class ChatKind { NORMAL, OPEN, ANON }

    @Test
    fun `enum 을 값으로 넘기면 이름 그대로 찍힌다`() =
        assertEquals(
            "evt=MSG_SEND_OK kind=OPEN",
            f.body("MSG_SEND_OK", arrayOf("kind", ChatKind.OPEN)),
        )

    @Test
    fun `enum 은 같은 상수면 항상 같은 문자열이 된다`() {
        val a = f.body("X", arrayOf("kind", ChatKind.OPEN))
        val b = f.body("X", arrayOf("kind", ChatKind.valueOf("OPEN")))
        assertEquals(a, b)
    }

    @Test
    fun `자유 문자열은 대소문자가 다르면 다른 값이 된다 - enum 을 써야 하는 이유`() {
        val upper = f.body("X", arrayOf("kind", "OPEN"))
        val lower = f.body("X", arrayOf("kind", "open"))
        assertNotEquals(upper, lower)
    }
}
