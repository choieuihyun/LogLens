package io.loglens.core

import java.util.Random
import java.util.concurrent.atomic.AtomicInteger

/**
 * 원문(요청·응답 본문)을 로그 줄에 싣는 규칙입니다.
 *
 * ```
 * evt=ADDR_ADD_RES flowId=a1 plId=k31 plPart=1 plParts=2 plBytes=5120 | {"result":"ok","list":[...
 * evt=ADDR_ADD_RES flowId=a1 plId=k31 plPart=2 plParts=2 plBytes=5120 | ...]}
 * ```
 *
 * 세 가지를 지킵니다.
 *
 * 1. **조각 하나하나가 온전한 레코드입니다.** 큰 본문은 여러 줄로 나뉘지만 줄마다 `evt=` 로
 *    시작하고 필드를 전부 다시 싣습니다. "한 줄 = 한 레코드" 는 그대로이고, 첫 조각이
 *    유실돼도 나머지가 스스로를 설명합니다. 그래서 원문 줄에는 `...[cut]` 이 붙지 않습니다.
 * 2. **되돌릴 수 있게 싣습니다.** 일반 메시지는 줄바꿈을 `\n` 두 글자로 바꾸기만 해서, JSON 안에
 *    원래 있던 `\n` 과 구분이 안 됩니다. 원문은 백슬래시부터 이스케이프해서 뷰어가 정확히 되돌립니다.
 * 3. **본문 안의 민감 키도 가립니다.** [Masker] 의 키와 이름이 정확히 같은 것만 가립니다.
 *    정규식과 간단한 훑기로 하는 최선의 노력이라, 이것만 믿고 인증 응답을 실으면 안 됩니다.
 *
 * 계약 전문은 docs/RECORD_FORMAT.md 8절.
 */
object Payload {

    /** 한 번에 싣는 본문의 상한(UTF-8 바이트). 넘는 부분은 버리고 `plCut` 으로 알립니다. */
    const val DEFAULT_MAX_TOTAL_BYTES = 64 * 1024

    const val F_ID = "plId"
    const val F_PART = "plPart"
    const val F_PARTS = "plParts"
    const val F_BYTES = "plBytes"
    const val F_CUT = "plCut"
    const val F_ERR = "plErr"

    /** 조각 가장자리 보정(공백, `]`)이 늘릴 수 있는 바이트. 조각 크기를 잴 때 미리 빼 둡니다. */
    internal const val EDGE_SLACK = 16

    /** 머리가 아무리 길어도 조각 하나에 이만큼은 싣습니다. */
    internal const val MIN_CHUNK_BYTES = 16

    /** `pl` 뒤에 대문자가 오는 이름(`plId`, `plPart` …)은 라이브러리가 씁니다. `place` 는 아닙니다. */
    @JvmStatic
    fun isReserved(key: String): Boolean =
        key.length > 2 && key[0] == 'p' && key[1] == 'l' && key[2] in 'A'..'Z'

    // 프로세스마다 다른 두 글자 + 36진 순번. 앱을 다시 띄워도 앞 실행의 묶음과 겹치기 어렵습니다.
    private val RUN = Integer.toString(Random().nextInt(36 * 36), 36).padStart(2, '0')
    private val SEQ = AtomicInteger()

    @JvmStatic
    fun nextId(): String = RUN + Integer.toString(SEQ.incrementAndGet(), 36)

    // ── 이스케이프 ──────────────────────────────────────────────────────────

    /**
     * 조각 하나를 한 줄에 실을 수 있게 바꿉니다. [unescape] 로 정확히 되돌아옵니다.
     *
     * - `\` → `\\` (가장 먼저. 이게 없으면 원래 있던 `\n` 과 구분이 안 됩니다)
     * - 줄바꿈·CR·탭 → `\n` `\r` `\t`
     * - 그 밖의 제어문자, 줄을 가르는 U+2028/U+2029, 짝 없는 서로게이트 → `\uXXXX`
     * - 조각의 **맨 앞·맨 뒤**가 공백이면 그 글자만 `\s`(스페이스) 또는 `\uXXXX`.
     *   파서가 줄 끝 공백을 떼어 내기 때문입니다. 안쪽 공백과 `|` 는 그대로 둡니다.
     */
    @JvmStatic
    fun escape(chunk: String): String {
        if (chunk.isEmpty()) return chunk
        val sb = StringBuilder(chunk.length + 16)
        val n = chunk.length
        var i = 0
        while (i < n) {
            val cp = chunk.codePointAt(i)
            val len = Character.charCount(cp)
            val edge = i == 0 || i + len >= n
            when {
                cp == '\\'.code -> sb.append("\\\\")
                cp == '\n'.code -> sb.append("\\n")
                cp == '\r'.code -> sb.append("\\r")
                cp == '\t'.code -> sb.append("\\t")
                needsUnicodeEscape(cp) -> appendUnicode(sb, cp)
                edge && cp == ' '.code -> sb.append("\\s")
                edge && isSpace(cp) -> appendUnicode(sb, cp)
                else -> sb.appendCodePoint(cp)
            }
            i += len
        }
        // 조각이 우연히 "...[cut]" 로 끝나면 뷰어가 잘린 줄로 봅니다. 마지막 글자만 바꿔 둡니다.
        if (sb.endsWith(Truncator.MARK)) {
            sb.setLength(sb.length - 1)
            appendUnicode(sb, ']'.code)
        }
        return sb.toString()
    }

    /** [escape] 의 반대. 모르는 이스케이프는 그대로 둡니다. */
    @JvmStatic
    fun unescape(s: String): String {
        if (s.indexOf('\\') < 0) return s
        val sb = StringBuilder(s.length)
        val n = s.length
        var i = 0
        while (i < n) {
            val c = s[i]
            if (c != '\\' || i + 1 >= n) {
                sb.append(c)
                i++
                continue
            }
            val e = s[i + 1]
            when (e) {
                '\\' -> sb.append('\\')
                'n' -> sb.append('\n')
                'r' -> sb.append('\r')
                't' -> sb.append('\t')
                's' -> sb.append(' ')
                'u' -> {
                    val hex = if (i + 6 <= n) s.substring(i + 2, i + 6) else ""
                    val v = if (hex.length == 4) hex.toIntOrNull(16) else null
                    if (v != null) {
                        sb.append(v.toChar())
                        i += 6
                        continue
                    }
                    sb.append(c).append(e)
                }
                else -> sb.append(c).append(e)
            }
            i += 2
        }
        return sb.toString()
    }

    private fun needsUnicodeEscape(cp: Int): Boolean =
        cp < 0x20 || cp in 0x7F..0x9F || cp == 0x2028 || cp == 0x2029 || cp in 0xD800..0xDFFF

    private fun isSpace(cp: Int): Boolean = Character.isWhitespace(cp) || Character.isSpaceChar(cp)

    private fun appendUnicode(sb: StringBuilder, cp: Int) {
        sb.append("\\u")
        val hex = Integer.toHexString(cp).uppercase()
        for (k in hex.length until 4) sb.append('0')
        sb.append(hex)
    }

    /** 글자 하나가 이스케이프 뒤 차지하는 UTF-8 바이트 수 (가장자리 보정은 [EDGE_SLACK] 이 따로 덮습니다). */
    private fun escapedWidth(cp: Int): Int = when {
        cp == '\\'.code || cp == '\n'.code || cp == '\r'.code || cp == '\t'.code -> 2
        needsUnicodeEscape(cp) -> 6
        cp < 0x80 -> 1
        cp < 0x800 -> 2
        cp < 0x10000 -> 3
        else -> 4
    }

    // ── 자르기 ──────────────────────────────────────────────────────────────

    /** 본문을 [maxBytes] 이하로 줄입니다. 글자 중간에서 끊지 않습니다. */
    @JvmStatic
    fun cap(text: String, maxBytes: Int): String {
        if (maxBytes <= 0) return ""
        if (text.length <= maxBytes / 4) return text      // 글자당 최대 4바이트이니 확실히 안 넘습니다
        var bytes = 0
        var i = 0
        while (i < text.length) {
            val cp = text.codePointAt(i)
            val w = if (cp < 0x80) 1 else if (cp < 0x800) 2 else if (cp < 0x10000) 3 else 4
            if (bytes + w > maxBytes) return text.substring(0, i)
            bytes += w
            i += Character.charCount(cp)
        }
        return text
    }

    /**
     * 이스케이프한 뒤의 크기가 [budget] 바이트를 넘지 않게 본문을 나눕니다.
     * 이스케이프하기 **전**의 글자 경계에서 나누므로 이스케이프가 두 조각에 걸칠 일이 없습니다.
     * 빈 본문도 조각 하나(빈 문자열)를 돌려줍니다.
     */
    @JvmStatic
    fun split(text: String, budget: Int): List<String> {
        val out = ArrayList<String>()
        var start = 0
        var bytes = 0
        var i = 0
        while (i < text.length) {
            val cp = text.codePointAt(i)
            val w = escapedWidth(cp)
            if (bytes + w > budget && i > start) {
                out.add(text.substring(start, i))
                start = i
                bytes = 0
            }
            bytes += w
            i += Character.charCount(cp)
        }
        if (start < text.length || out.isEmpty()) out.add(text.substring(start))
        return out
    }

    // ── 본문 안 민감 키 가리기 ──────────────────────────────────────────────

    private val XML_ELEM = Regex(
        """<((?:[A-Za-z_][\w.\-]*:)?([A-Za-z_][\w.\-]*))(\s[^<>]*)?>((?:<!\[CDATA\[[\s\S]*?]]>)|[^<]*)</\1\s*>"""
    )
    private val ATTR = Regex("""([A-Za-z_][\w.\-]*)(\s*=\s*)("[^"]*"|'[^']*')""")
    private val FORM = Regex("""(^|[?&])([A-Za-z_][\w.\-]*)=([^&\s"'<>\\]*)""")

    /**
     * 본문 안에서 민감 키의 값을 `***` 로 바꿉니다. 키 이름이 **정확히** 같을 때만 가립니다.
     *
     * 보는 모양: JSON 의 `"키": 값`(값이 객체·배열이면 통째로), 문자열 안에 한 번 더 싸인 JSON 의
     * `\"키\": \"값\"`, XML 의 `<키>값</키>` 와 `키="값"`, 주소·폼의 `키=값`.
     */
    @JvmStatic
    fun mask(text: String, masker: Masker): String {
        if (text.isEmpty()) return text
        var s = maskQuoted(text, masker, "\"")
        if (s.contains("\\\"")) s = maskQuoted(s, masker, "\\\"")
        if (s.indexOf('<') >= 0) {
            s = XML_ELEM.replace(s) { m ->
                if (!masker.isSensitive(m.groupValues[2])) m.value
                else "<${m.groupValues[1]}${m.groupValues[3]}>${Masker.MASK}</${m.groupValues[1]}>"
            }
        }
        if (s.indexOf('=') >= 0) {
            s = ATTR.replace(s) { m ->
                if (!masker.isSensitive(localName(m.groupValues[1]))) m.value
                else {
                    val q = m.groupValues[3][0]
                    "${m.groupValues[1]}${m.groupValues[2]}$q${Masker.MASK}$q"
                }
            }
            s = FORM.replace(s) { m ->
                if (!masker.isSensitive(m.groupValues[2])) m.value
                else "${m.groupValues[1]}${m.groupValues[2]}=${Masker.MASK}"
            }
        }
        return s
    }

    private fun localName(name: String): String = name.substringAfterLast(':')

    /**
     * 따옴표 [q] 로 싸인 키 뒤에 `:` 가 오면 키-값으로 보고, 민감 키면 값을 가립니다.
     * [q] 가 `"` 면 보통 JSON, `\"` 면 문자열 안에 한 번 더 싸인 JSON 입니다.
     * 정규식을 쓰지 않는 이유: 긴 문자열에서 정규식 엔진이 스택을 다 쓰는 경우가 있습니다.
     */
    private fun maskQuoted(s: String, masker: Masker, q: String): String {
        val n = s.length
        val plain = q.length == 1
        var sb: StringBuilder? = null
        var last = 0
        var i = s.indexOf(q)
        while (i in 0 until n) {
            val end = closing(s, i + q.length, q, plain)
            if (end < 0) break
            var j = skipWs(s, end + q.length)
            if (j < n && s[j] == ':') {
                j = skipWs(s, j + 1)
                if (masker.isSensitive(s.substring(i + q.length, end))) {
                    val ve = valueEnd(s, j, q, plain)
                    val out = sb ?: StringBuilder(n).also { sb = it }
                    out.append(s, last, j).append(q).append(Masker.MASK).append(q)
                    last = ve
                    i = s.indexOf(q, ve)
                    continue
                }
                i = s.indexOf(q, j)
                continue
            }
            i = s.indexOf(q, end + q.length)
        }
        val out = sb ?: return s
        return out.append(s, last, n).toString()
    }

    /** 닫는 따옴표의 위치. 없으면 -1. 보통 JSON 에서는 `\"` 를 건너뜁니다. */
    private fun closing(s: String, from: Int, q: String, plain: Boolean): Int {
        if (!plain) return s.indexOf(q, from)
        var i = from
        while (i < s.length) {
            when (s[i]) {
                '\\' -> i += 2
                '"' -> return i
                else -> i++
            }
        }
        return -1
    }

    private fun skipWs(s: String, from: Int): Int {
        var i = from
        while (i < s.length && (s[i] == ' ' || s[i] == '\t' || s[i] == '\n' || s[i] == '\r')) i++
        return i
    }

    /** 값이 끝나는 자리. 닫히지 않았으면 끝까지 가립니다 (덜 가리는 것보다 낫습니다). */
    private fun valueEnd(s: String, from: Int, q: String, plain: Boolean): Int {
        val n = s.length
        if (from >= n) return n
        if (s.startsWith(q, from)) {
            val e = closing(s, from + q.length, q, plain)
            return if (e < 0) n else e + q.length
        }
        val c = s[from]
        if (c == '{' || c == '[') {
            var depth = 0
            var i = from
            while (i < n) {
                val ch = s[i]
                if (plain && ch == '"') {
                    val e = closing(s, i + 1, q, true)
                    if (e < 0) return n
                    i = e + 1
                    continue
                }
                if (ch == '{' || ch == '[') depth++
                if (ch == '}' || ch == ']') {
                    depth--
                    if (depth == 0) return i + 1
                }
                i++
            }
            return n
        }
        var i = from
        while (i < n) {
            val ch = s[i]
            if (ch == ',' || ch == '}' || ch == ']' || ch == '"' || ch == '\\' ||
                ch == ' ' || ch == '\t' || ch == '\n' || ch == '\r'
            ) break
            i++
        }
        return i
    }
}
