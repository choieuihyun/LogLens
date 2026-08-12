package io.loglens.android;

import android.util.Log;

import io.loglens.core.Level;
import io.loglens.core.Sink;

/**
 * 기본 싱크 — logcat.
 *
 * <p><b>태그를 메시지 본문에 넣지 않는다.</b> 이게 이 프로젝트의 출발점이다.
 * 흔한 사내 래퍼들이 {@code Log.d("APP", "[AUTH] 로그인 성공")} 처럼 찍는 바람에
 * logcat 의 태그 필터({@code -s APP_AUTH:*})가 무력화된다. 우리는 도메인을 태그 자리에
 * 그대로 둔다 — 그래야 도메인 필터가 공짜로 따라온다.
 */
public final class LogcatSink implements Sink {

    @Override
    public void write(Level level, String tag, String body) {
        switch (level) {
            case V: Log.v(tag, body); break;
            case D: Log.d(tag, body); break;
            case I: Log.i(tag, body); break;
            case W: Log.w(tag, body); break;
            case E: Log.e(tag, body); break;
        }
    }
}
