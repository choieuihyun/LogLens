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
    //
    // ThreadLocal.withInitial() 을 쓰지 않는 이유: 자바 8 API 지만 안드로이드에서는
    // **API 26 부터** 존재한다. minSdk 21 을 선언해 놓고 그걸 쓰면 API 21~25 기기에서
    // 클래스 로딩 시점에 NoSuchMethodError 로 죽는다. 익명 서브클래스는 어디서나 된다.
    private static final ThreadLocal<SimpleDateFormat> FMT = new ThreadLocal<SimpleDateFormat>() {
        @Override protected SimpleDateFormat initialValue() {
            return new SimpleDateFormat(TS_PATTERN, Locale.US);
        }
    };

    private LineFormat() {}

    public static String render(Level level, String tag, String body) {
        return timestamp() + " " + level.c + "/" + tag + ": " + body;
    }

    public static String timestamp() {
        return FMT.get().format(new Date());
    }
}
