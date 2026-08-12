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

    override fun write(level: Level, tag: String, body: String) {
        when (level) {
            Level.V -> Log.v(tag, body)
            Level.D -> Log.d(tag, body)
            Level.I -> Log.i(tag, body)
            Level.W -> Log.w(tag, body)
            Level.E -> Log.e(tag, body)
        }
    }
}
