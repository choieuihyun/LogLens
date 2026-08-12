package io.loglens.core;

import java.util.ArrayList;
import java.util.List;

/**
 * 파사드. call site 가 보는 전부.
 *
 * <pre>{@code
 * LogLens.init(BuildConfig.DEBUG);                 // 앱이 빌드타입을 주입한다
 * LogLens.addSink(new LogcatSink());
 *
 * LogLens.i(AppDomain.AUTH, "LOGIN_OK", "uid", uid);
 * LogLens.e(AppDomain.NET, "SOCKET_FAIL", e, "host", host);
 * LogLens.d(AppDomain.CHAT, "ROOM_ENTER");
 * LogLens.i(AppDomain.AUTH, "LOGIN_FAIL", "reason", r, "msg", "비밀번호 불일치");
 * }</pre>
 *
 * <h2>왜 varargs 키-값 쌍인가</h2>
 * 채택되지 않는 로깅 표준은 존재하지 않는 것과 같다. {@code Log.d(TAG, "..")} 대비
 * 마찰이 조금이라도 크면 개발자는 그냥 안 쓴다. 빌더 패턴({@code .field().field().log()})은
 * 타입 안전하지만 장황해서 기각했다.
 *
 * <p>대가: 키-값 짝이 컴파일 타임에 보장되지 않는다. 이건 {@code init(isDebug=true)} 일 때
 * 홀수 인자를 시끄럽게 경고하는 것으로 보완한다 — 개발 중에 반드시 걸린다.
 *
 * <h2>릴리스 게이팅</h2>
 * {@code init()} 을 부르기 전 기본값은 <b>디버그 아님</b>이다. 초기화를 잊었을 때
 * V/D 가 새는 것보다 조용히 빠지는 쪽이 안전하다.
 */
public final class LogLens {

    private static volatile boolean debug = false;      // 안전 기본값
    private static volatile Formatter formatter = new Formatter();
    private static final List<Sink> SINKS = new ArrayList<>();

    private LogLens() {}

    // ── 설정 ────────────────────────────────────────────────────────────────

    /**
     * @param isDebug 앱의 디버그 빌드 여부. <b>앱이 주입해야 한다.</b>
     *                라이브러리 모듈의 {@code BuildConfig.DEBUG} 는 자기 모듈의 빌드타입이라
     *                앱이 릴리스여도 true 일 수 있다 (기획서 §5의 함정).
     */
    public static synchronized void init(boolean isDebug) {
        debug = isDebug;
        formatter = new Formatter(new Masker(), Truncator.DEFAULT_MAX_BYTES, diagnostics());
    }

    /** 마스킹 정책까지 갈아끼우는 초기화. */
    public static synchronized void init(boolean isDebug, Masker masker, int maxBytes) {
        debug = isDebug;
        formatter = new Formatter(masker, maxBytes, diagnostics());
    }

    public static synchronized void addSink(Sink sink) {
        if (sink != null) SINKS.add(sink);
    }

    public static synchronized void clearSinks() {
        for (Sink s : SINKS) s.close();
        SINKS.clear();
    }

    public static boolean isDebug() {
        return debug;
    }

    private static Formatter.Diagnostics diagnostics() {
        return debug ? m -> System.err.println("[LogLens] " + m) : Formatter.Diagnostics.SILENT;
    }

    // ── 로깅 API ────────────────────────────────────────────────────────────

    public static void v(LogDomain d, String event, Object... kv) { log(Level.V, d, event, null, kv); }
    public static void d(LogDomain d, String event, Object... kv) { log(Level.D, d, event, null, kv); }
    public static void i(LogDomain d, String event, Object... kv) { log(Level.I, d, event, null, kv); }
    public static void w(LogDomain d, String event, Object... kv) { log(Level.W, d, event, null, kv); }
    public static void e(LogDomain d, String event, Object... kv) { log(Level.E, d, event, null, kv); }

    /** 예외 오버로드. {@code err=} / {@code at=} 필드로 접혀 들어간다. */
    public static void w(LogDomain d, String event, Throwable t, Object... kv) { log(Level.W, d, event, t, kv); }
    public static void e(LogDomain d, String event, Throwable t, Object... kv) { log(Level.E, d, event, t, kv); }

    // ── 내부 ────────────────────────────────────────────────────────────────

    static void log(Level level, LogDomain domain, String event, Throwable t, Object... kv) {
        if (!level.enabled(debug)) return;          // 릴리스에서 V/D 는 문자열 조립조차 안 한다
        if (domain == null) return;
        List<Sink> sinks;
        Formatter f;
        synchronized (LogLens.class) {
            if (SINKS.isEmpty()) return;
            sinks = new ArrayList<>(SINKS);
            f = formatter;
        }
        String body = f.body(event, kv, t);
        String tag = domain.tag();
        for (Sink s : sinks) {
            try {
                s.write(level, tag, body);
            } catch (Throwable ignored) {
                // 로깅이 앱을 죽이면 안 된다.
            }
        }
    }

    /** 테스트/왕복검증용: 싱크를 거치지 않고 본문만 얻는다. */
    public static String render(String event, Throwable t, Object... kv) {
        return formatter.body(event, kv, t);
    }
}
