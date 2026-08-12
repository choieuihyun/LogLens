package io.loglens.core

/**
 * logcat 이 자르기 전에 우리가 먼저 자릅니다. **글자 단위로** 자릅니다.
 *
 * logcat 은 한 줄이 4KB 근처를 넘으면 알아서 잘라 버립니다. 우리가 먼저 자르지 않으면
 * 어디서 잘릴지 모르고, 파서는 반쯤 뜯긴 줄을 받게 됩니다.
 *
 * 핵심은 **바이트로 세되 글자로 자르는** 것입니다. 한글은 UTF-8 에서 3바이트라서
 * `getBytes()[0..n]` 으로 그냥 자르면 글자가 반으로 갈려 깨지거나 디코딩이 실패합니다.
 * 이모지(서로게이트 페어)는 더 심합니다.
 *
 * 여러 줄로 쪼개지 않는 이유: 로그 한 줄이 레코드 하나라는 게 약속이기 때문입니다.
 * 쪼개는 순간 파서가 두 번째 줄부터를 이해하지 못합니다. 그래서 **자르고 표시합니다.**
 */
object Truncator {

    /** 잘렸다는 표시. 뷰어가 이걸 보고 [cut] 배지를 답니다. */
    const val MARK = "...[cut]"

    /** logcat 한 줄의 안전 한도(바이트). 실제 한계(약 4076)보다 여유를 뒀습니다. */
    const val DEFAULT_MAX_BYTES = 3800

    private val MARK_BYTES = MARK.toByteArray(Charsets.UTF_8).size

    @JvmStatic
    @JvmOverloads
    fun truncate(s: String?, maxBytes: Int = DEFAULT_MAX_BYTES): String? {
        if (s == null) return null
        if (maxBytes <= MARK_BYTES) return MARK
        if (utf8Length(s) <= maxBytes) return s

        val budget = maxBytes - MARK_BYTES
        var bytes = 0
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            val w = utf8Width(cp)
            if (bytes + w > budget) break
            bytes += w
            i += Character.charCount(cp)   // 서로게이트 페어를 통째로 넘깁니다
        }
        return s.substring(0, i) + MARK
    }

    @JvmStatic
    fun isTruncated(s: String?): Boolean = s != null && s.endsWith(MARK)

    @JvmStatic
    fun utf8Length(s: String): Int {
        var n = 0
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            n += utf8Width(cp)
            i += Character.charCount(cp)
        }
        return n
    }

    private fun utf8Width(cp: Int): Int = when {
        cp < 0x80 -> 1
        cp < 0x800 -> 2
        cp < 0x10000 -> 3
        else -> 4
    }
}
