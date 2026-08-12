package io.loglens.demo;

import io.loglens.core.LogLens;
import io.loglens.sample.AppDomainJava;

/**
 * <b>자바 호출부</b> — 라이브러리가 Kotlin 이어도 자바에서 그대로 씁니다.
 *
 * <p>이 파일이 컴파일된다는 것 자체가 검증입니다. Kotlin 전용 오버로드에는
 * {@code @JvmSynthetic} 이 붙어 있어서 자바에는 보이지 않고, 자바용 가변 인자
 * 오버로드만 노출됩니다. 그래서 예전 자바 코드와 문법이 완전히 같습니다.
 *
 * <p>UCWORKS 처럼 자바가 대부분인 프로젝트를 위한 경로입니다.
 */
public final class JavaCallSite {

    private JavaCallSite() {}

    static void javaStyleCall() {
        // Kotlin 의 "uid" to uid 와 결과가 똑같습니다. new Pair<>() 를 쓸 필요가 없습니다.
        LogLens.i(AppDomainJava.CHAT, "MSG_SEND_OK", "room", 3, "len", 42);

        LogLens.e(AppDomainJava.NET, "REQUEST_FAIL",
                new java.net.ConnectException("timeout"),
                "host", "api.example.test", "code", 500);

        LogLens.d(AppDomainJava.CHAT, "ROOM_ENTER");
    }
}
