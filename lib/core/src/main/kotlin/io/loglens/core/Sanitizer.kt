package io.loglens.core

/**
 * 값과 메시지를 형식에 맞게 정리합니다.
 *
 * 여기서 지키는 규칙: **값에는 공백도, 파이프도, 줄바꿈도 없습니다.**
 * 줄바꿈이 특히 위험합니다 — 로그 한 줄이 레코드 하나라는 전제가 깨지면
 * 그 뒤로 전부 어긋납니다. 공백은 그다음 문제입니다(필드 경계가 밀립니다).
 */
object Sanitizer {

    /** 값이 비었을 때 넣는 문자. `k=` 는 형식 위반이라 그 줄의 등급이 낮아집니다. */
    const val EMPTY = "-"

    /** 키가 규칙에 맞는지: `[A-Za-z_][A-Za-z0-9_]*` */
    @JvmStatic
    fun isValidKey(key: String?): Boolean {
        if (key.isNullOrEmpty()) return false
        val c0 = key[0]
        if (!(c0.isAsciiLetter() || c0 == '_')) return false
        for (i in 1 until key.length) {
            val c = key[i]
            if (!(c.isAsciiLetter() || c.isAsciiDigit() || c == '_')) return false
        }
        return true
    }

    /**
     * 값 정리: 줄바꿈과 탭은 두 글자 이스케이프로, 공백은 `_` 로, `|` 는 `/` 로 바꿉니다.
     * 결과는 반드시 공백 없는 한 덩어리입니다.
     */
    @JvmStatic
    fun value(raw: Any?): String {
        if (raw == null) return EMPTY
        val s = raw.toString()
        if (s.isEmpty()) return EMPTY

        val sb = StringBuilder(s.length + 8)
        for (c in s) {
            when {
                c == '\n' -> sb.append("\\n")
                c == '\r' -> sb.append("\\r")
                c == '\t' -> sb.append("\\t")
                c == '|' -> sb.append('/')
                // 공백류(스페이스, NBSP 등)는 전부 언더스코어로. 제어문자는 버립니다.
                c.isWhitespace() -> sb.append('_')
                c.isISOControl() -> Unit
                else -> sb.append(c)
            }
        }
        val out = sb.toString()
        // 전부 공백이었던 경우
        return if (out.replace("_", "").isEmpty()) EMPTY else out
    }

    /**
     * 자유 메시지 정리: 공백과 `|` 는 살려두고 줄바꿈류만 처리합니다.
     * (`|` 는 첫 번째 것만 구분자로 쓰이므로 뒤쪽 파이프는 메시지의 일부로 남습니다.)
     */
    @JvmStatic
    fun message(raw: String?): String? {
        if (raw == null) return null
        val sb = StringBuilder(raw.length + 8)
        for (c in raw) {
            when {
                c == '\n' -> sb.append("\\n")
                c == '\r' -> sb.append("\\r")
                c == '\t' -> sb.append("\\t")
                c.isISOControl() -> Unit
                else -> sb.append(c)
            }
        }
        return sb.toString().trim().ifEmpty { null }
    }

    /** 이벤트 이름 정리. 값과 같은 규칙이고, 관례상 대문자 SNAKE_CASE 를 권합니다. */
    @JvmStatic
    fun event(raw: String?): String {
        val v = value(raw)
        return if (v == EMPTY) "UNKNOWN" else v
    }

    private fun Char.isAsciiLetter() = this in 'a'..'z' || this in 'A'..'Z'
    private fun Char.isAsciiDigit() = this in '0'..'9'
    private fun Char.isISOControl() = this.code < 0x20 || this.code in 0x7F..0x9F
}
