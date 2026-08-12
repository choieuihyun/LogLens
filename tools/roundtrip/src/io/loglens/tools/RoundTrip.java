package io.loglens.tools;

import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import io.loglens.core.Formatter;
import io.loglens.core.LineFormat;
import io.loglens.core.Level;
import io.loglens.core.LogDomain;
import io.loglens.core.Masker;
import io.loglens.core.Sanitizer;
import io.loglens.core.Truncator;

/**
 * 왕복 검증 생성기 — 계약의 양쪽이 정말 같은 문법을 쓰는지 확인한다.
 *
 * <p>손으로 쓴 픽스처는 <b>양쪽에 같은 실수를 심을 수 있다.</b> 내가 파서를 잘못
 * 이해한 채로 픽스처를 쓰면 파서는 통과한다. 그래서 진짜 검증은 이것이다:
 *
 * <pre>
 *   Java Formatter --생성--> 한 줄 --> Python Parser --> 필드 비교
 * </pre>
 *
 * <p>이 프로그램은 케이스마다 세 줄을 stdout 으로 낸다 (탭 구분):
 * <pre>
 *   CASE  &lt;이름&gt;  &lt;모드: EXACT|TRUNC&gt;
 *   CANON &lt;domain&gt;|&lt;event&gt;|&lt;k=v,k=v&gt;|&lt;msg&gt;
 *   LINE  &lt;렌더된 한 줄&gt;
 * </pre>
 * {@code tools/roundtrip/verify.py} 가 이걸 받아 파싱하고 CANON 과 대조한다.
 *
 * <p>CANON 은 Formatter 의 출력을 되읽어 만든 게 아니라 <b>입력으로부터 독립적으로</b>
 * 만든다. 그래야 대조에 의미가 있다.
 */
public final class RoundTrip {

    enum D implements LogDomain {
        AUTH, CHAT, NET, FILE_XFER, API2;
        public String tag() { return "APP_" + name(); }
    }

    static final Formatter F = new Formatter(new Masker(), Truncator.DEFAULT_MAX_BYTES,
            Formatter.Diagnostics.SILENT);
    static final Masker M = new Masker();

    static PrintStream out;

    public static void main(String[] args) {
        out = new PrintStream(new java.io.FileOutputStream(java.io.FileDescriptor.out),
                true, StandardCharsets.UTF_8);

        emit("평범한 레코드", Level.I, D.AUTH, "LOGIN_OK", null, "uid", 123, "msg", "로그인 성공");
        emit("이벤트만", Level.D, D.CHAT, "ROOM_ENTER", null);
        emit("필드만", Level.E, D.NET, "SOCKET_FAIL", null, "host", "10.0.0.1", "code", 500);
        emit("메시지만", Level.I, D.CHAT, "MSG_SEND", null, "msg", "그냥 메시지");
        emit("도메인에 언더스코어", Level.I, D.FILE_XFER, "UPLOAD_DONE", null, "size", 1048576);
        emit("도메인에 숫자", Level.I, D.API2, "CALL_OK", null, "code", 200);

        emit("빈 값 센티널", Level.I, D.NET, "X", null, "a", null, "b", "", "c", "   ");
        emit("값 속 공백", Level.I, D.FILE_XFER, "UPLOAD_DONE", null, "name", "내 문서.pdf");
        emit("값 속 개행", Level.W, D.NET, "X", null, "dump", "line1\nline2");
        emit("값 속 파이프", Level.W, D.NET, "X", null, "expr", "a|b");
        emit("값 속 탭", Level.W, D.NET, "X", null, "t", "a\tb");
        emit("한글 값", Level.I, D.AUTH, "PROFILE", null, "name", "최의현");
        emit("이모지 값", Level.I, D.CHAT, "REACT", null, "emoji", "👍🏻");

        emit("마스킹", Level.W, D.AUTH, "TOKEN_REFRESH", null,
                "token", "eyJhbGciOiJIUzI1NiJ9.abc", "uid", 7);
        emit("과잉마스킹 안 함", Level.I, D.AUTH, "LOGIN_OK", null,
                "authType", "oauth2", "tokenCount", 3, "emailVerified", true);

        emit("메시지 속 파이프는 살아남는다", Level.I, D.NET, "X", null, "msg", "a | b | c");
        emit("메시지 속 등호", Level.I, D.NET, "X", null, "msg", "k=v 처럼 보이는 문장");
        emit("메시지 속 개행", Level.I, D.NET, "X", null, "msg", "첫줄\n둘째줄");
        emit("메시지가 evt= 로 시작", Level.I, D.NET, "X", null, "msg", "evt=FAKE");

        emit("예외", Level.E, D.CHAT, "SEND_FAIL", new IllegalStateException("session closed"),
                "room", 3);
        emit("메시지 없는 예외", Level.E, D.NET, "BOOM", new NullPointerException());

        emit("퍼널 상관ID", Level.I, D.AUTH, "LOGIN_START", null, "flowId", "f1001", "uid", 42);

        // 잘림 케이스 — 필드 값이 통째로 날아가므로 EXACT 대조는 불가.
        // 대신 "한 줄 유지 / 바이트 한도 / 파서가 안 죽음" 을 본다.
        emitTrunc("긴 ASCII 잘림", Level.V, D.NET, "TRACE", "payload", rep("a", 8000));
        emitTrunc("긴 한글 잘림", Level.V, D.NET, "TRACE", "payload", rep("한글", 4000));
        emitTrunc("긴 이모지 잘림", Level.V, D.NET, "TRACE", "payload", rep("👍", 3000));
        emitTrunc("긴 메시지 잘림", Level.V, D.NET, "TRACE", "msg", rep("긴 메시지 ", 2000));
    }

    // ── emit ────────────────────────────────────────────────────────────────

    static void emit(String name, Level lv, D domain, String event, Throwable t, Object... kv) {
        String body = F.body(event, kv, t);
        String mode = Truncator.isTruncated(body) ? "TRUNC" : "EXACT";
        out.println("CASE\t" + name + "\t" + mode);
        out.println("CANON\t" + canon(domain, event, t, kv));
        out.println("LINE\t" + LineFormat.render(lv, domain.tag(), body));
    }

    static void emitTrunc(String name, Level lv, D domain, String event, Object... kv) {
        String body = F.body(event, kv, null);
        out.println("CASE\t" + name + "\tTRUNC");
        out.println("CANON\t" + domain.name() + "|" + Sanitizer.event(event) + "||");
        out.println("LINE\t" + LineFormat.render(lv, domain.tag(), body));
    }

    /**
     * 기대값을 <b>입력으로부터</b> 독립적으로 조립한다.
     * Formatter 의 출력을 되읽지 않는 게 핵심 — 그러면 자기 자신과 비교하는 꼴이 된다.
     */
    static String canon(D domain, String event, Throwable t, Object... kv) {
        Map<String, String> fields = new LinkedHashMap<>();
        String msg = null;

        int pairs = kv == null ? 0 : (kv.length / 2) * 2;
        for (int i = 0; i < pairs; i += 2) {
            String k = kv[i] == null ? null : String.valueOf(kv[i]);
            if (!Sanitizer.isValidKey(k)) continue;
            if (Formatter.MSG_KEY.equals(k)) {
                msg = kv[i + 1] == null ? null : String.valueOf(kv[i + 1]);
                continue;
            }
            fields.put(k, M.apply(k, Sanitizer.value(kv[i + 1])));
        }
        if (t != null) {
            fields.put("err", Sanitizer.value(Formatter.describe(t)));
            String frame = Formatter.topFrame(t);
            if (frame != null) fields.put("at", Sanitizer.value(frame));
        }

        List<String> parts = new ArrayList<>();
        for (Map.Entry<String, String> e : fields.entrySet()) {
            parts.add(e.getKey() + "=" + e.getValue());
        }
        String sanitizedMsg = Sanitizer.message(msg);
        return domain.name() + "|" + Sanitizer.event(event) + "|"
                + String.join(",", parts) + "|" + (sanitizedMsg == null ? "" : sanitizedMsg);
    }

    static String rep(String s, int n) {
        StringBuilder sb = new StringBuilder(s.length() * n);
        for (int i = 0; i < n; i++) sb.append(s);
        return sb.toString();
    }
}
