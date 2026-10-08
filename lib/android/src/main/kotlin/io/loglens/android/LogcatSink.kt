package io.loglens.android

import android.util.Log
import io.loglens.core.Level
import io.loglens.core.Sink

/**
 * 기본 출력 대상 — logcat.
 *
 * **태그를 본문에 넣지 않습니다.** 이게 이 프로젝트의 출발점입니다.
 * 흔한 사내 래퍼들이 `Log.d("APP", "[AUTH] 로그인 성공")` 처럼 찍는 바람에
 * logcat 의 태그 필터(`-s APP_AUTH:*`)가 무의미해집니다.
 * 우리는 도메인을 태그 자리에 그대로 둡니다 — 그래야 도메인 필터가 공짜로 따라옵니다.
 */
class LogcatSink : Sink {

    /**
     * `adb shell setprop log.tag.UC_CHAT VERBOSE` 로 켜 둔 도메인인가.
     *
     * 앱이 릴리스 정책에서 런타임 스위치를 허용했을 때만 쓰입니다
     * (`ReleasePolicy.withRuntimeSwitch()`). 기본 정책에서는 릴리스에서 아무것도 나가지 않습니다.
     */
    override fun isForcedOn(level: Level, tag: String): Boolean =
        Log.isLoggable(tag, priorityOf(level))

    /** logcat 은 링버퍼라 기기에 오래 남지 않습니다. 원문을 받습니다 (디버그 빌드에서만 옵니다). */
    override fun acceptsPayload(): Boolean = true

    override fun write(level: Level, tag: String, body: String) {
        when (level) {
            Level.V -> Log.v(tag, body)
            Level.D -> Log.d(tag, body)
            Level.I -> Log.i(tag, body)
            Level.W -> Log.w(tag, body)
            Level.E -> Log.e(tag, body)
        }
    }

    private fun priorityOf(level: Level): Int = when (level) {
        Level.V -> Log.VERBOSE
        Level.D -> Log.DEBUG
        Level.I -> Log.INFO
        Level.W -> Log.WARN
        Level.E -> Log.ERROR
    }
}
