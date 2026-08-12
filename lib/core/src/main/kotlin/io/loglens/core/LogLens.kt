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
 * ## 릴리스에서 로그가 새지 않게
 *
 * [init] 을 부르기 전 기본값은 **디버그 아님**입니다. 초기화를 깜빡했을 때
 * V/D 가 새는 것보다 조용히 안 찍히는 쪽이 안전합니다.
 */
object LogLens {

    @Volatile
    private var debug = false                       // 안전한 기본값

    @Volatile
    private var formatter = Formatter()

    private val sinks = mutableListOf<Sink>()

    // ── 설정 ────────────────────────────────────────────────────────────────

    /**
     * @param isDebug 앱이 디버그 빌드인지. **앱이 알려줘야 합니다.**
     *   라이브러리 모듈의 `BuildConfig.DEBUG` 는 그 라이브러리의 빌드 타입이라,
     *   앱을 release 로 빌드해도 true 로 남을 수 있습니다.
     */
    @JvmStatic
    @Synchronized
    fun init(isDebug: Boolean) {
        debug = isDebug
        formatter = Formatter(Masker(), Truncator.DEFAULT_MAX_BYTES, diagnostics())
    }

    /** 마스킹 정책과 길이 한도까지 바꾸는 초기화. */
    @JvmStatic
    @Synchronized
    fun init(isDebug: Boolean, masker: Masker, maxBytes: Int) {
        debug = isDebug
        formatter = Formatter(masker, maxBytes, diagnostics())
    }

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
        // 릴리스에서 V/D 는 문자열을 만들지도 않습니다.
        if (!level.enabled(debug)) return

        val snapshot: List<Sink>
        val f: Formatter
        synchronized(this) {
            if (sinks.isEmpty()) return
            snapshot = ArrayList(sinks)
            f = formatter
        }

        val body = f.body(event, kv, t)
        val tag = domain.tag()
        for (s in snapshot) {
            try {
                s.write(level, tag, body)
            } catch (ignored: Throwable) {
                // 로그 때문에 앱이 죽으면 안 됩니다.
            }
        }
    }

    /** 테스트와 대조 검증용: 출력 대상을 거치지 않고 본문만 얻습니다. */
    @JvmStatic
    @JvmOverloads
    fun render(event: String, t: Throwable? = null, vararg kv: Any?): String =
        formatter.body(event, kv, t)
}
