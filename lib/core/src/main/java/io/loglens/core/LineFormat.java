package io.loglens.core;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/**
 * 파일/콘솔 싱크의 줄 접두사.
 *
 * <pre>
 *   2026-08-12 11:23:45.678 I/APP_AUTH: evt=...
 * </pre>
 *
 * <p>logcat 의 접두사는 안드로이드가 만든다(우리는 {@code -v threadtime} 로 고정만 한다).
 * 파일 싱크의 접두사는 <b>우리가 소유</b>하므로 연도를 포함시킨다 — 날짜별 파일을
 * 나중에 합쳐 볼 때 연도가 없으면 정렬이 애매해진다.
 *
 * <p>뷰어 파서의 {@code filesink} 접두사 패턴과 한 쌍이다.
 * 여길 바꾸면 docs/RECORD_FORMAT.md §3 과 parser.py 의 패턴도 같이 바꿔야 한다.
 */
public final class LineFormat {

    public static final String TS_PATTERN = "yyyy-MM-dd HH:mm:ss.SSS";

    // SimpleDateFormat 은 스레드 세이프하지 않다.
    private static final ThreadLocal<SimpleDateFormat> FMT =
            ThreadLocal.withInitial(() -> new SimpleDateFormat(TS_PATTERN, Locale.US));

    private LineFormat() {}

    public static String render(Level level, String tag, String body) {
        return timestamp() + " " + level.c + "/" + tag + ": " + body;
    }

    public static String timestamp() {
        return FMT.get().format(new Date());
    }
}
