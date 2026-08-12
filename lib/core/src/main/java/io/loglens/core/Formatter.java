package io.loglens.core;

/**
 * 레코드 본문 조립기 — 계약의 emitter 쪽 구현.
 *
 * <pre>
 *   evt=&lt;EVENT&gt; k=v k=v | &lt;free message&gt;
 * </pre>
 *
 * <p>순수 문자열 로직이다. 안드로이드 의존이 전혀 없어서 일반 JVM 에서 그대로
 * 단위 테스트할 수 있고, 뷰어 파서와의 왕복 검증도 여기서 돌린다.
 */
public final class Formatter {

    /** 이 키로 넘긴 값은 필드가 아니라 {@code | } 뒤 자유 메시지가 된다. */
    public static final String MSG_KEY = "msg";

    private final Masker masker;
    private final int maxBytes;
    private final Diagnostics diag;

    /** 규격 위반을 개발자에게 알리는 통로. 릴리스에서는 무음. */
    public interface Diagnostics {
        void warn(String message);
        Diagnostics SILENT = m -> { };
    }

    public Formatter() {
        this(new Masker(), Truncator.DEFAULT_MAX_BYTES, Diagnostics.SILENT);
    }

    public Formatter(Masker masker, int maxBytes, Diagnostics diag) {
        this.masker = masker == null ? new Masker() : masker;
        this.maxBytes = maxBytes;
        this.diag = diag == null ? Diagnostics.SILENT : diag;
    }

    /**
     * 본문을 만든다.
     *
     * @param event 이벤트 코드 (대문자 SNAKE_CASE 권장)
     * @param kv    키-값 쌍의 varargs. 홀수면 마지막 키는 버리고 경고한다.
     * @param t     예외 (없으면 null). {@code err=} / {@code at=} 필드로 접힌다.
     */
    public String body(String event, Object[] kv, Throwable t) {
        StringBuilder sb = new StringBuilder(96);
        sb.append("evt=").append(Sanitizer.event(event));

        String freeMsg = null;

        if (kv != null && kv.length > 0) {
            if (kv.length % 2 != 0) {
                // 컴파일 타임에는 못 잡는다(varargs 의 대가). 개발 중에 시끄럽게 알린다.
                diag.warn("키-값 인자 개수가 홀수입니다 (" + kv.length + "). "
                        + "마지막 인자 '" + kv[kv.length - 1] + "' 를 버립니다. evt=" + event);
            }
            int pairs = (kv.length / 2) * 2;
            for (int i = 0; i < pairs; i += 2) {
                String key = kv[i] == null ? null : String.valueOf(kv[i]);
                if (!Sanitizer.isValidKey(key)) {
                    diag.warn("잘못된 키 '" + key + "' — 이 쌍을 건너뜁니다. evt=" + event);
                    continue;
                }
                if (MSG_KEY.equals(key)) {
                    freeMsg = kv[i + 1] == null ? null : String.valueOf(kv[i + 1]);
                    continue;
                }
                String value = masker.apply(key, Sanitizer.value(kv[i + 1]));
                sb.append(' ').append(key).append('=').append(value);
            }
        }

        if (t != null) {
            sb.append(' ').append("err=").append(Sanitizer.value(describe(t)));
            String frame = topFrame(t);
            if (frame != null) sb.append(' ').append("at=").append(Sanitizer.value(frame));
        }

        String msg = Sanitizer.message(freeMsg);
        if (msg != null) sb.append(" | ").append(msg);

        return Truncator.truncate(sb.toString(), maxBytes);
    }

    /** {@code ConnectException:timeout} 형태. 예외 메시지 원문을 통째로 덤프하지 않는다. */
    public static String describe(Throwable t) {
        String name = t.getClass().getSimpleName();
        String m = t.getMessage();
        if (m == null || m.isEmpty()) return name;
        // 메시지에 응답 본문이 통째로 실려오는 경우가 있다 (기획서 §9-3). 앞부분만.
        if (m.length() > 120) m = m.substring(0, 120);
        return name + ":" + m;
    }

    /** 앱 코드의 첫 스택 프레임. 한 줄 안에서 "어디서 터졌나"를 알려준다. */
    public static String topFrame(Throwable t) {
        StackTraceElement[] st = t.getStackTrace();
        if (st == null || st.length == 0) return null;
        StackTraceElement e = st[0];
        String cls = e.getClassName();
        int dot = cls.lastIndexOf('.');
        if (dot >= 0) cls = cls.substring(dot + 1);
        return cls + "." + e.getMethodName() + ":" + e.getLineNumber();
    }
}
