package io.loglens.core;

/**
 * 값/키/메시지 정화. 계약(docs/RECORD_FORMAT.md §4 I5)의 emitter 쪽 절반.
 *
 * <p>여기서 지키는 불변식: <b>값에는 공백도, 파이프도, 개행도 없다.</b>
 * 개행이 진짜 파서 킬러다 — 한 줄 = 한 레코드가 깨지면 그 뒤 모든 게 어긋난다.
 * 공백은 그다음 문제다(필드 경계가 밀린다).
 */
public final class Sanitizer {

    /** 값이 비었을 때 쓰는 센티널. {@code k=} 는 문법 위반이라 파서가 레코드를 강등시킨다. */
    public static final String EMPTY = "-";

    private Sanitizer() {}

    /** 키가 규격에 맞는가: {@code [A-Za-z_][A-Za-z0-9_]*} */
    public static boolean isValidKey(String key) {
        if (key == null || key.isEmpty()) return false;
        char c0 = key.charAt(0);
        if (!(Character.isLetter(c0) && c0 < 128) && c0 != '_') return false;
        for (int i = 1; i < key.length(); i++) {
            char c = key.charAt(i);
            boolean ok = (c < 128 && (Character.isLetterOrDigit(c))) || c == '_';
            if (!ok) return false;
        }
        return true;
    }

    /**
     * 값 정화: 개행/탭은 리터럴 이스케이프로, 공백은 {@code _} 로, {@code |} 는 {@code /} 로.
     * 결과는 반드시 공백 없는 한 덩어리 토큰이다.
     */
    public static String value(Object raw) {
        if (raw == null) return EMPTY;
        String s = String.valueOf(raw);
        if (s.isEmpty()) return EMPTY;

        StringBuilder sb = new StringBuilder(s.length() + 8);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                case '|':  sb.append('/');   break;
                default:
                    // 공백류(스페이스, NBSP, …)는 전부 언더스코어로. 제어문자는 버린다.
                    if (Character.isWhitespace(c)) sb.append('_');
                    else if (Character.isISOControl(c)) { /* drop */ }
                    else sb.append(c);
            }
        }
        String out = sb.toString();
        // 전부 공백이었던 경우
        return out.replace("_", "").isEmpty() ? EMPTY : out;
    }

    /**
     * 자유 메시지 정화: 공백과 {@code |} 는 살려두고 개행류만 잡는다.
     * ({@code |} 는 첫 번째 것만 구분자로 쓰이므로 뒤쪽 파이프는 메시지의 일부로 살아남는다.)
     */
    public static String message(String raw) {
        if (raw == null) return null;
        StringBuilder sb = new StringBuilder(raw.length() + 8);
        for (int i = 0; i < raw.length(); i++) {
            char c = raw.charAt(i);
            switch (c) {
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (Character.isISOControl(c)) { /* drop */ }
                    else sb.append(c);
            }
        }
        String out = sb.toString().trim();
        return out.isEmpty() ? null : out;
    }

    /** 이벤트 코드 정화. 값과 같은 규칙이되 관례상 대문자 SNAKE_CASE 를 권장한다. */
    public static String event(String raw) {
        String v = value(raw);
        return EMPTY.equals(v) ? "UNKNOWN" : v;
    }
}
