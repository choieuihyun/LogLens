package io.loglens.core

/**
 * 호출부가 쓰는 진입점입니다.
 *
 * ### Kotlin
 * ```
 * LogLens.init(BuildConfig.DEBUG)
 * LogLens.addSink(LogcatSink())
 *
 * LogLens.i(AppDomain.AUTH, "LOGIN_OK", "uid" to uid, "msg" to "로그인 성공")
 * LogLens.e(AppDomain.NET, "SOCKET_FAIL", e, "host" to host)
 * LogLens.d(AppDomain.CHAT, "ROOM_ENTER")
 * ```
 *
 * ### Java
 * ```java
 * LogLens.i(AppDomain.AUTH, "LOGIN_OK", "uid", uid, "msg", "로그인 성공");
 * LogLens.e(AppDomain.NET, "SOCKET_FAIL", e, "host", host);
 * LogLens.d(AppDomain.CHAT, "ROOM_ENTER");
 * ```
 *
 * ## 왜 API 가 두 벌인가
 *
 * Kotlin 에서는 `"uid" to uid` 로 넘길 수 있어서 **키-값 짝이 컴파일 시점에 보장**됩니다.
 * 인자 개수를 홀수로 쓰는 실수 자체가 불가능합니다.
 *
 * 그런데 자바에는 `to` 같은 infix 문법이 없어서, 같은 API 를 쓰려면 필드마다
 * `new Pair<>("uid", uid)` 를 써야 합니다. 자바가 대부분인 프로젝트에서는 마찰이 큽니다.
 * 그래서 자바용으로 기존 가변 인자 형태를 그대로 남겨 뒀습니다.
 *
 * Kotlin 전용 오버로드에는 `@JvmSynthetic` 이 붙어 있어서 자바에서는 아예 보이지 않습니다.
 * 두 오버로드가 자바 쪽에서 충돌하는 걸 막기 위해서입니다.
 *
 * ## 릴리스에서는 기본으로 아무것도 찍지 않습니다
 *
 * 디버그 빌드가 아니면 레벨과 상관없이 **한 줄도** 내보내지 않습니다.
 * [init] 을 부르기 전 기본값도 **디버그 아님**입니다. 초기화를 깜빡했을 때
 * 로그가 새는 것보다 조용히 안 찍히는 쪽이 안전합니다.
 *
 * 릴리스에서도 경고·에러를 받아 봐야 하는 앱은 초기화할 때 [ReleasePolicy] 를 골라 엽니다.
 * 원문([payload])은 무엇을 고르든 릴리스에서 나가지 않습니다.
 */
object LogLens {

    @Volatile
    private var debug = false                       // 안전한 기본값

    @Volatile
    private var release = ReleasePolicy.SILENT      // 안전한 기본값: 릴리스에서는 아무것도

    @Volatile
    private var formatter = Formatter()

    @Volatile
    private var payloadMaxBytes = Payload.DEFAULT_MAX_TOTAL_BYTES

    private val sinks = mutableListOf<Sink>()

    // ── 설정 ────────────────────────────────────────────────────────────────

    /**
     * @param isDebug 앱이 디버그 빌드인지. **앱이 알려줘야 합니다.**
     *   라이브러리 모듈의 `BuildConfig.DEBUG` 는 그 라이브러리의 빌드 타입이라,
     *   앱을 release 로 빌드해도 true 로 남을 수 있습니다.
     */
    @JvmStatic
    @Synchronized
    fun init(isDebug: Boolean) = init(isDebug, ReleasePolicy.SILENT)

    /**
     * 릴리스에서 무엇을 내보낼지까지 고르는 초기화. 고르지 않으면 [ReleasePolicy.SILENT] 입니다.
     */
    @JvmStatic
    @Synchronized
    fun init(isDebug: Boolean, release: ReleasePolicy) =
        init(isDebug, Masker(), Truncator.DEFAULT_MAX_BYTES, release)

    /** 마스킹 정책과 길이 한도까지 바꾸는 초기화. */
    @JvmStatic
    @JvmOverloads
    @Synchronized
    fun init(
        isDebug: Boolean,
        masker: Masker,
        maxBytes: Int,
        release: ReleasePolicy = ReleasePolicy.SILENT,
    ) {
        debug = isDebug
        this.release = release
        formatter = Formatter(masker, maxBytes, diagnostics())
    }

    /** 지금 적용된 릴리스 정책. */
    @JvmStatic
    fun releasePolicy(): ReleasePolicy = release

    @JvmStatic
    @Synchronized
    fun addSink(sink: Sink) {
        sinks.add(sink)
    }

    @JvmStatic
    @Synchronized
    fun clearSinks() {
        sinks.forEach { it.close() }
        sinks.clear()
    }

    @JvmStatic
    fun isDebug(): Boolean = debug

    /** 원문 하나에 싣는 본문의 상한(UTF-8 바이트). 기본 64KB. 넘는 부분은 버리고 표시합니다. */
    @JvmStatic
    fun setPayloadMaxBytes(bytes: Int) {
        payloadMaxBytes = if (bytes > 0) bytes else Payload.DEFAULT_MAX_TOTAL_BYTES
    }

    private fun diagnostics(): Formatter.Diagnostics =
        if (debug) Formatter.Diagnostics { System.err.println("[LogLens] $it") }
        else Formatter.Diagnostics.SILENT

    // ── 필드 없음 (두 언어 공통) ────────────────────────────────────────────
    // 가변 인자 오버로드가 둘이라, 인자가 없을 때 어느 쪽인지 애매해집니다.
    // 인자 없는 오버로드를 따로 두면 이쪽이 가장 구체적이라 항상 이깁니다.

    @JvmStatic fun v(domain: LogDomain, event: String) = log(Level.V, domain, event, null, null)
    @JvmStatic fun d(domain: LogDomain, event: String) = log(Level.D, domain, event, null, null)
    @JvmStatic fun i(domain: LogDomain, event: String) = log(Level.I, domain, event, null, null)
    @JvmStatic fun w(domain: LogDomain, event: String) = log(Level.W, domain, event, null, null)
    @JvmStatic fun e(domain: LogDomain, event: String) = log(Level.E, domain, event, null, null)

    // ── Java 용: 키와 값을 번갈아 넘깁니다 ──────────────────────────────────

    @JvmStatic fun v(domain: LogDomain, event: String, vararg kv: Any?) = log(Level.V, domain, event, null, kv)
    @JvmStatic fun d(domain: LogDomain, event: String, vararg kv: Any?) = log(Level.D, domain, event, null, kv)
    @JvmStatic fun i(domain: LogDomain, event: String, vararg kv: Any?) = log(Level.I, domain, event, null, kv)
    @JvmStatic fun w(domain: LogDomain, event: String, vararg kv: Any?) = log(Level.W, domain, event, null, kv)
    @JvmStatic fun e(domain: LogDomain, event: String, vararg kv: Any?) = log(Level.E, domain, event, null, kv)

    @JvmStatic
    fun w(domain: LogDomain, event: String, t: Throwable, vararg kv: Any?) =
        log(Level.W, domain, event, t, kv)

    @JvmStatic
    fun e(domain: LogDomain, event: String, t: Throwable, vararg kv: Any?) =
        log(Level.E, domain, event, t, kv)

    // ── Kotlin 용: 키-값 짝이 컴파일 시점에 보장됩니다 ──────────────────────
    // @JvmSynthetic 을 붙여 자바에서는 안 보이게 합니다 (위 오버로드와 충돌 방지).

    @JvmSynthetic
    fun v(domain: LogDomain, event: String, vararg fields: Pair<String, Any?>) =
        log(Level.V, domain, event, null, fields.flatten())

    @JvmSynthetic
    fun d(domain: LogDomain, event: String, vararg fields: Pair<String, Any?>) =
        log(Level.D, domain, event, null, fields.flatten())

    @JvmSynthetic
    fun i(domain: LogDomain, event: String, vararg fields: Pair<String, Any?>) =
        log(Level.I, domain, event, null, fields.flatten())

    @JvmSynthetic
    fun w(domain: LogDomain, event: String, vararg fields: Pair<String, Any?>) =
        log(Level.W, domain, event, null, fields.flatten())

    @JvmSynthetic
    fun e(domain: LogDomain, event: String, vararg fields: Pair<String, Any?>) =
        log(Level.E, domain, event, null, fields.flatten())

    @JvmSynthetic
    fun w(domain: LogDomain, event: String, t: Throwable, vararg fields: Pair<String, Any?>) =
        log(Level.W, domain, event, t, fields.flatten())

    @JvmSynthetic
    fun e(domain: LogDomain, event: String, t: Throwable, vararg fields: Pair<String, Any?>) =
        log(Level.E, domain, event, t, fields.flatten())

    // ── 원문 (요청·응답 본문) ───────────────────────────────────────────────
    // 서버에서 받은 JSON·XML 을 통째로 남깁니다. 일반 로그와 다른 점:
    //   - 한도를 넘으면 잘리지 않고 여러 줄로 나뉩니다. 뷰어가 다시 합칩니다
    //   - 되돌릴 수 있게 이스케이프합니다 (줄바꿈·백슬래시가 그대로 돌아옵니다)
    //   - 본문 안의 민감 키도 가립니다 (최선의 노력입니다)
    //   - 받겠다고 밝힌 출력 대상에만 갑니다 (기본은 logcat. 파일에는 안 남습니다)
    // 로그인·토큰·인증 응답은 여기에도 싣지 마세요. 디버그 로그는 버그 리포트에 그대로 붙습니다.
    // 이벤트 이름은 요약 로그와 다르게 짓습니다 (예: ADDR_ADD_RES_BODY).

    @JvmStatic
    fun payload(domain: LogDomain, event: String, text: String?) =
        logPayload(domain, event, text, null)

    @JvmStatic
    fun payload(domain: LogDomain, event: String, text: String?, vararg kv: Any?) =
        logPayload(domain, event, text, kv)

    @JvmSynthetic
    fun payload(domain: LogDomain, event: String, text: String?, vararg fields: Pair<String, Any?>) =
        logPayload(domain, event, text, fields.flatten())

    // ── 내부 ────────────────────────────────────────────────────────────────

    private fun Array<out Pair<String, Any?>>.flatten(): Array<Any?> {
        val out = arrayOfNulls<Any?>(size * 2)
        forEachIndexed { idx, (k, v) ->
            out[idx * 2] = k
            out[idx * 2 + 1] = v
        }
        return out
    }

    private fun log(
        level: Level,
        domain: LogDomain,
        event: String,
        t: Throwable?,
        kv: Array<out Any?>?,
    ) {
        // 릴리스에서는 기본으로 아무것도 내보내지 않습니다 (ReleasePolicy.SILENT).
        // 여기서 끊기면 출력 대상도 보지 않고 문자열도 만들지 않습니다.
        val isDebug = debug
        val policy = release
        if (!isDebug && policy.isSilent()) return

        val snapshot: List<Sink>
        val f: Formatter
        synchronized(this) {
            if (sinks.isEmpty()) return
            snapshot = ArrayList(sinks)
            f = formatter
        }

        val tag = domain.tag()

        // 앱이 정책으로 열어 둔 경우에만: 레벨이 통과하거나, 출력 대상이 런타임으로 켜 뒀거나.
        // (logcat 은 `setprop log.tag.<태그> VERBOSE` 로 도메인 하나만 열 수 있습니다)
        val targets = when {
            isDebug || policy.passes(level) -> snapshot
            policy.runtimeSwitch -> snapshot.filter { asked { it.isForcedOn(level, tag) } }
            else -> return
        }
        if (targets.isEmpty()) return

        val body = f.body(event, kv, t)
        for (s in targets) {
            try {
                s.write(level, tag, body)
            } catch (ignored: Throwable) {
                // 로그 때문에 앱이 죽으면 안 됩니다.
            }
        }
    }

    /** 출력 대상에게 묻다가 예외가 나면 "아니오" 로 칩니다. 로그 때문에 앱이 죽으면 안 됩니다. */
    private inline fun asked(question: () -> Boolean): Boolean =
        try {
            question()
        } catch (ignored: Throwable) {
            false
        }

    private fun logPayload(domain: LogDomain, event: String, text: String?, kv: Array<out Any?>?) {
        // 릴리스에서는 본문을 만들지도 않습니다. 릴리스 정책(ReleasePolicy)을 무엇으로 골랐든,
        // 출력 대상이 런타임으로 켜 달라고 하든 원문은 열리지 않습니다.
        if (!debug) return

        val targets: List<Sink>
        val f: Formatter
        synchronized(this) {
            targets = sinks.filter { asked { it.acceptsPayload() } }
            f = formatter
        }
        if (targets.isEmpty()) return

        val tag = domain.tag()
        val lines = try {
            f.payload(event, text, kv, payloadMaxBytes)
        } catch (ignored: Throwable) {
            return                                  // 로그 때문에 앱이 죽으면 안 됩니다.
        }
        for (s in targets) {
            try {
                for (body in lines) s.write(Level.D, tag, body)
            } catch (ignored: Throwable) {
            }
        }
    }

    /** 테스트와 대조 검증용: 출력 대상을 거치지 않고 본문만 얻습니다. */
    @JvmStatic
    @JvmOverloads
    fun render(event: String, t: Throwable? = null, vararg kv: Any?): String =
        formatter.body(event, kv, t)
}
