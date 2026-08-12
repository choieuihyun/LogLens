package io.loglens.core;

import java.io.PrintStream;

/**
 * 표준출력 싱크. JVM 단위 테스트, 데스크톱 데모, 그리고 뷰어와의 왕복 검증에 쓴다.
 * 파일 싱크와 <b>같은 접두사 포맷</b>을 낸다 — 파서 하나로 둘 다 읽힌다.
 */
public final class ConsoleSink implements Sink {

    private final PrintStream out;

    public ConsoleSink() { this(System.out); }

    public ConsoleSink(PrintStream out) { this.out = out; }

    @Override
    public void write(Level level, String tag, String body) {
        out.println(LineFormat.render(level, tag, body));
        out.flush();
    }
}
