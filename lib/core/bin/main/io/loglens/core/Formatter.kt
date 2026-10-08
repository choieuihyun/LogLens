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

    /**
     * 원문을 싣는 줄들을 만듭니다. 한도를 넘으면 여러 줄로 나뉘고, 줄마다 온전한 본문입니다.
     *
     * 일반 로그와 다른 점: 길이 자르기([Truncator])를 거치지 않습니다. 줄이 한도를 넘지 않게
     * 나눠 담기 때문에 `...[cut]` 이 붙을 일이 없습니다. 규칙은 [Payload] 에 있습니다.
     *
     * @param text          원문. 서버에서 받은 그대로 넘깁니다 (들여쓰기를 넣거나 줄이지 않습니다)
     * @param kv            함께 실을 필드. 조각마다 전부 반복됩니다. `msg` 와 `pl…` 이름은 쓸 수 없습니다
     * @param maxTotalBytes 본문 상한. 넘는 부분은 버리고 `plCut=<원래 크기>` 로 알립니다
     * @param id            묶음 id. 테스트에서 고정하려고 받습니다
     */
    @JvmOverloads
    fun payload(
        event: String?,
        text: String?,
        kv: Array<out Any?>? = null,
        maxTotalBytes: Int = Payload.DEFAULT_MAX_TOTAL_BYTES,
        id: String = Payload.nextId(),
    ): List<String> {
        val raw = text ?: ""
        val evt = "evt=" + Sanitizer.event(event)
        var fields = payloadFields(event, kv)

        // 가리기는 자르기보다 먼저 합니다. 먼저 자르면 닫는 따옴표가 사라진 값이 안 가려진 채 남습니다.
        // 아주 큰 본문은 상한의 네 배까지만 보고 가립니다 (남길 부분은 그보다 훨씬 앞쪽입니다).
        var err: String? = null
        val scanLimit = maxTotalBytes.toLong() * 4
        val scanned = if (raw.length > scanLimit) raw.substring(0, safeEnd(raw, scanLimit.toInt())) else raw
        val masked = try {
            Payload.mask(scanned, masker)
        } catch (t: Throwable) {
            // 못 가렸으면 싣지 않습니다. 가려지지 않은 본문이 나가는 것보다 낫습니다.
            err = "mask"
            ""
        }
        val kept = Payload.cap(masked, maxTotalBytes)
        val cut = err == null && (kept.length < masked.length || scanned.length < raw.length)

        val tail = StringBuilder(48)
        tail.append(' ').append(Payload.F_BYTES).append('=').append(Truncator.utf8Length(kept))
        if (cut) tail.append(' ').append(Payload.F_CUT).append('=').append(Truncator.utf8Length(raw))
        if (err != null) tail.append(' ').append(Payload.F_ERR).append('=').append(err)

        // 머리가 줄의 대부분을 차지하면 본문이 잘게 부서집니다. 그럴 때는 호출부 필드를 뺍니다.
        fun fixed(f: String) = Truncator.utf8Length(evt) + Truncator.utf8Length(f) +
            " ${Payload.F_ID}=".length + Truncator.utf8Length(id) +
            " ${Payload.F_PART}=".length + " ${Payload.F_PARTS}=".length + tail.length + SEP.length
        val room = maxBytes - fixed(fields)
        if (fields.isNotEmpty() && room < MIN_ROOM && room < (maxBytes - fixed("")) / 2) {
            diag.warn("원문 로그의 필드가 너무 길어 뺐습니다. evt=$event")
            fields = ""
        }

        // 조각 수의 자릿수가 머리 길이를 바꾸므로, 맞을 때까지 다시 나눕니다 (보통 한두 번).
        var digits = 1
        var chunks: List<String>
        while (true) {
            val budget = maxBytes - fixed(fields) - digits * 2 - Payload.EDGE_SLACK
            chunks = Payload.split(kept, maxOf(budget, Payload.MIN_CHUNK_BYTES))
            val need = chunks.size.toString().length
            if (need <= digits) break
            digits = need
        }

        val head = "$evt$fields ${Payload.F_ID}=$id"
        return chunks.mapIndexed { idx, c ->
            val sb = StringBuilder(head.length + c.length + 64)
            sb.append(head)
                .append(' ').append(Payload.F_PART).append('=').append(idx + 1)
                .append(' ').append(Payload.F_PARTS).append('=').append(chunks.size)
                .append(tail)
            if (c.isNotEmpty()) sb.append(SEP).append(Payload.escape(c))
            sb.toString()
        }
    }

    /** 원문 줄에 함께 실을 필드. 일반 로그와 같은 규칙으로 정리하고 가립니다. */
    private fun payloadFields(event: String?, kv: Array<out Any?>?): String {
        if (kv == null || kv.isEmpty()) return ""
        if (kv.size % 2 != 0) {
            diag.warn(
                "키-값 인자 개수가 홀수입니다 (${kv.size}). " +
                    "마지막 인자 '${kv.last()}' 를 버립니다. evt=$event"
            )
        }
        val sb = StringBuilder(64)
        val pairs = (kv.size / 2) * 2
        var i = 0
        while (i < pairs) {
            val key = kv[i]?.toString()
            when {
                !Sanitizer.isValidKey(key) ->
                    diag.warn("잘못된 키 '$key' — 이 쌍을 건너뜁니다. evt=$event")
                key == MSG_KEY ->
                    diag.warn("원문 로그에는 msg 를 따로 줄 수 없습니다 (그 자리에 원문이 들어갑니다). evt=$event")
                Payload.isReserved(key!!) ->
                    diag.warn("'$key' 는 원문 로그가 쓰는 이름입니다 — 이 쌍을 건너뜁니다. evt=$event")
                else ->
                    sb.append(' ').append(key).append('=')
                        .append(masker.apply(key, Sanitizer.value(kv[i + 1])))
            }
            i += 2
        }
        return sb.toString()
    }

    /** [limit] 근처에서 서로게이트 짝을 가르지 않는 자리. */
    private fun safeEnd(s: String, limit: Int): Int =
        if (limit in 1 until s.length && Character.isHighSurrogate(s[limit - 1])) limit - 1 else limit

    companion object {
        /** 본문과 자유 메시지를 가르는 자리. */
        private const val SEP = " | "

        /** 원문 줄에서 본문에 남길 자리. 이보다 좁고, 필드가 그 자리의 절반 넘게 먹으면 호출부 필드를 뺍니다. */
        private const val MIN_ROOM = 256

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
