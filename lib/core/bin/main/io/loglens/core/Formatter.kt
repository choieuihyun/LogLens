package io.loglens.core

/**
 * 로그 본문을 조립합니다.
 *
 * ```
 * evt=<이벤트> 키=값 키=값 | <자유 메시지>
 * ```
 *
 * 순수 문자열 로직입니다. 안드로이드 의존이 전혀 없어서 일반 JVM 에서 그대로
 * 테스트할 수 있고, 뷰어 파서와 대조하는 검증도 여기서 돌립니다.
 */
class Formatter @JvmOverloads constructor(
    private val masker: Masker = Masker(),
    private val maxBytes: Int = Truncator.DEFAULT_MAX_BYTES,
    private val diag: Diagnostics = Diagnostics.SILENT,
) {

    /** 형식 위반을 개발자에게 알리는 통로입니다. 릴리스에서는 아무것도 하지 않습니다. */
    fun interface Diagnostics {
        fun warn(message: String)

        companion object {
            @JvmField
            val SILENT = Diagnostics { }
        }
    }

    /**
     * 본문을 만듭니다.
     *
     * @param event 이벤트 이름 (대문자 SNAKE_CASE 권장)
     * @param kv    키-값 쌍이 번갈아 들어옵니다. 개수가 홀수면 마지막 키는 버리고 경고합니다.
     * @param t     예외 (없으면 null). `err=` / `at=` 필드로 접혀 들어갑니다.
     */
    @JvmOverloads
    fun body(event: String?, kv: Array<out Any?>? = null, t: Throwable? = null): String {
        val sb = StringBuilder(96)
        sb.append("evt=").append(Sanitizer.event(event))

        var freeMsg: String? = null

        if (kv != null && kv.isNotEmpty()) {
            if (kv.size % 2 != 0) {
                // 컴파일 시점에는 못 잡습니다(가변 인자의 대가). 개발 중에 시끄럽게 알립니다.
                diag.warn(
                    "키-값 인자 개수가 홀수입니다 (${kv.size}). " +
                        "마지막 인자 '${kv.last()}' 를 버립니다. evt=$event"
                )
            }
            val pairs = (kv.size / 2) * 2
            var i = 0
            while (i < pairs) {
                val key = kv[i]?.toString()
                if (!Sanitizer.isValidKey(key)) {
                    diag.warn("잘못된 키 '$key' — 이 쌍을 건너뜁니다. evt=$event")
                    i += 2
                    continue
                }
                if (key == MSG_KEY) {
                    freeMsg = kv[i + 1]?.toString()
                    i += 2
                    continue
                }
                sb.append(' ').append(key).append('=')
                    .append(masker.apply(key, Sanitizer.value(kv[i + 1])))
                i += 2
            }
        }

        if (t != null) {
            sb.append(' ').append("err=").append(Sanitizer.value(describe(t)))
            topFrame(t)?.let { sb.append(' ').append("at=").append(Sanitizer.value(it)) }
        }

        Sanitizer.message(freeMsg)?.let { sb.append(" | ").append(it) }

        return Truncator.truncate(sb.toString(), maxBytes)!!
    }

    companion object {
        /** 이 키로 넘긴 값은 필드가 아니라 `| ` 뒤의 자유 메시지가 됩니다. */
        const val MSG_KEY = "msg"

        /** `ConnectException:timeout` 형태. 예외 메시지를 통째로 덤프하지 않습니다. */
        @JvmStatic
        fun describe(t: Throwable): String {
            val name = t.javaClass.simpleName
            var m = t.message
            if (m.isNullOrEmpty()) return name
            // 예외 메시지에 응답 본문이 통째로 실려 오는 경우가 있습니다. 앞부분만 씁니다.
            if (m.length > 120) m = m.substring(0, 120)
            return "$name:$m"
        }

        /** 스택의 첫 프레임. 한 줄 안에서 "어디서 터졌나"를 알려 줍니다. */
        @JvmStatic
        fun topFrame(t: Throwable): String? {
            val e = t.stackTrace?.firstOrNull() ?: return null
            val cls = e.className.substringAfterLast('.')
            return "$cls.${e.methodName}:${e.lineNumber}"
        }
    }
}
