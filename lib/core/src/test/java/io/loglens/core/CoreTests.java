package io.loglens.core;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;

/**
 * core 단위 테스트.
 *
 * <p>JUnit 없이 돈다 — 이 모듈은 안드로이드도, 서드파티도 모르는 순수 자바다.
 * 그 순수함을 테스트 하네스에도 지켰다. {@code javac} + {@code java} 만 있으면 검증된다.
 *
 * <pre>  make test-lib  </pre>
 */
public final class CoreTests {

    private static int passed = 0;
    private static int failed = 0;

    public static void main(String[] args) throws Exception {
        sanitizer();
        masker();
        truncator();
        formatter();
        levels();
        facade();
        fileSink();

        System.out.println();
        System.out.printf("core: %d passed, %d failed%n", passed, failed);
        if (failed > 0) System.exit(1);
    }

    // ── Sanitizer ───────────────────────────────────────────────────────────
    static void sanitizer() {
        section("Sanitizer");
        eq("공백은 언더스코어로", "a_b", Sanitizer.value("a b"));
        eq("개행은 리터럴 이스케이프로", "a\\nb", Sanitizer.value("a\nb"));
        eq("CR/탭도", "a\\rb\\tc", Sanitizer.value("a\rb\tc"));
        eq("파이프는 슬래시로", "a/b", Sanitizer.value("a|b"));
        eq("null 은 센티널", "-", Sanitizer.value(null));
        eq("빈 문자열도 센티널", "-", Sanitizer.value(""));
        eq("공백뿐이어도 센티널", "-", Sanitizer.value("   "));
        eq("한글은 그대로", "로그인성공", Sanitizer.value("로그인성공"));
        eq("숫자 타입도 처리", "42", Sanitizer.value(42));

        String v = Sanitizer.value("a b\nc|d\te");
        ok("정화된 값에는 공백/파이프/개행이 없다",
                !v.contains(" ") && !v.contains("|") && v.indexOf('\n') < 0);

        eq("메시지는 공백을 살린다", "로그인 성공", Sanitizer.message("로그인 성공"));
        eq("메시지도 개행은 잡는다", "a\\nb", Sanitizer.message("a\nb"));
        eq("메시지는 파이프를 살린다", "a | b", Sanitizer.message("a | b"));
        ok("빈 메시지는 null", Sanitizer.message("   ") == null);

        ok("유효 키", Sanitizer.isValidKey("uid") && Sanitizer.isValidKey("_x")
                && Sanitizer.isValidKey("flowId2"));
        ok("숫자로 시작하는 키는 무효", !Sanitizer.isValidKey("2x"));
        ok("공백 든 키는 무효", !Sanitizer.isValidKey("a b"));
        ok("한글 키는 무효", !Sanitizer.isValidKey("사용자"));
        ok("빈 키는 무효", !Sanitizer.isValidKey(""));
    }

    // ── Masker ──────────────────────────────────────────────────────────────
    static void masker() {
        section("Masker");
        Masker m = new Masker();
        eq("token 은 가린다", "***", m.apply("token", "eyJhbGciOi"));
        eq("password 는 가린다", "***", m.apply("password", "hunter2"));
        eq("대소문자 무관", "***", m.apply("PassWord", "hunter2"));

        // 기획서 §9-2 의 실전 교훈. 이게 이 클래스의 존재 이유다.
        eq("authType 은 가리지 않는다 (부분일치 금지)", "oauth2", m.apply("authType", "oauth2"));
        eq("tokenCount 도 가리지 않는다", "3", m.apply("tokenCount", "3"));
        eq("emailVerified 도 가리지 않는다", "true", m.apply("emailVerified", "true"));
        eq("일반 키는 통과", "123", m.apply("uid", "123"));

        ok("커스텀 키 추가", m.plus("deviceSerial").isSensitive("deviceserial"));
        ok("추가해도 기본은 유지", m.plus("deviceSerial").isSensitive("token"));
        ok("마스크는 공백 없는 토큰", !Masker.MASK.contains(" "));
    }

    // ── Truncator ───────────────────────────────────────────────────────────
    static void truncator() {
        section("Truncator");
        eq("짧으면 그대로", "abc", Truncator.truncate("abc", 100));

        String ascii = repeat("a", 500);
        String cut = Truncator.truncate(ascii, 100);
        ok("ASCII: 한도 이내", Truncator.utf8Length(cut) <= 100);
        ok("ASCII: 표식 붙음", cut.endsWith(Truncator.MARK));

        // 한글 3바이트 — 순진하게 바이트로 자르면 여기서 깨진다
        String ko = repeat("한글로그메시지", 200);
        for (int max = 20; max <= 200; max += 7) {
            String c = Truncator.truncate(ko, max);
            int len = Truncator.utf8Length(c);
            ok("한글 max=" + max + ": 한도 이내 (" + len + ")", len <= max);
            String body = c.substring(0, c.length() - Truncator.MARK.length());
            ok("한글 max=" + max + ": 원문의 접두사", ko.startsWith(body));
            byte[] bytes = c.getBytes(StandardCharsets.UTF_8);
            String back = new String(bytes, StandardCharsets.UTF_8);
            ok("한글 max=" + max + ": UTF-8 왕복에서 안 깨짐", back.equals(c));
            ok("한글 max=" + max + ": 치환문자 없음", c.indexOf('\uFFFD') < 0);
        }

        // 이모지 = 4바이트 = 서로게이트 페어. 반으로 갈리면 lone surrogate 가 남는다.
        String emoji = repeat("👍", 100);
        for (int max = 20; max <= 120; max += 3) {
            String c = Truncator.truncate(emoji, max);
            ok("이모지 max=" + max + ": 한도 이내", Truncator.utf8Length(c) <= max);
            String body = c.substring(0, c.length() - Truncator.MARK.length());
            boolean lone = false;
            for (int i = 0; i < body.length(); i++) {
                char ch = body.charAt(i);
                if (Character.isHighSurrogate(ch)) {
                    if (i + 1 >= body.length() || !Character.isLowSurrogate(body.charAt(i + 1))) lone = true;
                    i++;
                } else if (Character.isLowSurrogate(ch)) lone = true;
            }
            ok("이모지 max=" + max + ": 서로게이트 페어가 안 쪼개짐", !lone);
        }

        ok("표식보다 작은 한도도 안 터짐", Truncator.truncate("긴문자열입니다", 3) != null);
        ok("isTruncated", Truncator.isTruncated("x" + Truncator.MARK));
    }

    // ── Formatter ───────────────────────────────────────────────────────────
    static void formatter() {
        section("Formatter");
        Formatter f = new Formatter();

        eq("이벤트만", "evt=ROOM_ENTER", f.body("ROOM_ENTER", null, null));
        eq("필드 하나", "evt=LOGIN_OK uid=123",
                f.body("LOGIN_OK", new Object[]{"uid", 123}, null));
        eq("필드 순서 유지", "evt=X a=1 b=2 c=3",
                f.body("X", new Object[]{"a", 1, "b", 2, "c", 3}, null));
        eq("msg 키는 자유 메시지로", "evt=LOGIN_OK uid=1 | 로그인 성공",
                f.body("LOGIN_OK", new Object[]{"uid", 1, "msg", "로그인 성공"}, null));
        eq("msg 만", "evt=PING | 안녕",
                f.body("PING", new Object[]{"msg", "안녕"}, null));
        eq("null 값은 센티널", "evt=X k=-",
                f.body("X", new Object[]{"k", null}, null));
        eq("값의 공백은 정화", "evt=X name=a_b",
                f.body("X", new Object[]{"name", "a b"}, null));
        eq("민감 키는 마스킹", "evt=T token=*** authType=oauth2",
                f.body("T", new Object[]{"token", "abc.def", "authType", "oauth2"}, null));

        // varargs 의 대가 — 컴파일 타임에 못 잡으니 런타임에 시끄럽게
        final StringBuilder warns = new StringBuilder();
        Formatter loud = new Formatter(new Masker(), Truncator.DEFAULT_MAX_BYTES, warns::append);
        eq("홀수 인자: 마지막을 버린다", "evt=X a=1",
                loud.body("X", new Object[]{"a", 1, "dangling"}, null));
        ok("홀수 인자: 경고한다", warns.toString().contains("홀수"));

        warns.setLength(0);
        eq("잘못된 키는 건너뛴다", "evt=X ok=1",
                loud.body("X", new Object[]{"bad key", "v", "ok", 1}, null));
        ok("잘못된 키: 경고한다", warns.toString().contains("잘못된 키"));

        Throwable t = new IllegalStateException("session closed");
        String withEx = f.body("SEND_FAIL", new Object[]{"room", 3}, t);
        ok("예외: err 필드", withEx.contains("err=IllegalStateException:session_closed"));
        ok("예외: at 필드", withEx.contains(" at=CoreTests."));
        ok("예외: 한 줄 유지", withEx.indexOf('\n') < 0);

        Throwable big = new RuntimeException(repeat("x", 500));
        ok("예외 메시지가 길어도 잘라 담는다",
                f.body("X", null, big).length() < 300);

        String longMsg = f.body("X", new Object[]{"msg", repeat("한글", 5000)}, null);
        ok("긴 본문은 잘린다", Truncator.isTruncated(longMsg));
        ok("잘려도 한도 이내", Truncator.utf8Length(longMsg) <= Truncator.DEFAULT_MAX_BYTES);
        ok("잘려도 한 줄", longMsg.indexOf('\n') < 0);
    }

    // ── Level ───────────────────────────────────────────────────────────────
    static void levels() {
        section("Level");
        ok("릴리스에서 V 차단", !Level.V.enabled(false));
        ok("릴리스에서 D 차단", !Level.D.enabled(false));
        ok("릴리스에서 I 통과", Level.I.enabled(false));
        ok("릴리스에서 W 통과", Level.W.enabled(false));
        ok("릴리스에서 E 통과", Level.E.enabled(false));
        ok("디버그에서 V 통과", Level.V.enabled(true));
    }

    // ── 파사드 ──────────────────────────────────────────────────────────────
    enum D implements LogDomain {
        AUTH, FILE_XFER;
        public String tag() { return "APP_" + name(); }
    }

    static void facade() {
        section("LogLens facade");
        MemorySink sink = new MemorySink();

        LogLens.clearSinks();
        LogLens.init(false);
        LogLens.addSink(sink);
        LogLens.v(D.AUTH, "TRACE");
        LogLens.d(D.AUTH, "DEBUG");
        LogLens.i(D.AUTH, "LOGIN_OK", "uid", 1);
        ok("릴리스: V/D 는 안 나가고 I 만", sink.size() == 1);

        sink.clear();
        LogLens.init(true);
        LogLens.v(D.AUTH, "TRACE");
        LogLens.d(D.AUTH, "DEBUG");
        ok("디버그: V/D 도 나간다", sink.size() == 2);

        sink.clear();
        LogLens.i(D.FILE_XFER, "UPLOAD_DONE", "size", 10, "name", "a.png");
        String line = sink.lines().get(0);
        ok("태그가 도메인이다", line.contains(" I/APP_FILE_XFER: "));
        ok("태그를 본문에 넣지 않는다", !sink.lastBody().contains("APP_FILE_XFER"));
        ok("접두사 포맷", line.matches("^\\d{4}-\\d\\d-\\d\\d \\d\\d:\\d\\d:\\d\\d\\.\\d{3} I/APP_FILE_XFER: evt=.*"));

        sink.clear();
        LogLens.addSink(new Sink() {
            public void write(Level l, String t, String b) { throw new RuntimeException("싱크 폭발"); }
        });
        LogLens.i(D.AUTH, "STILL_FINE");
        ok("싱크가 터져도 앱은 안 죽고 다른 싱크는 산다", sink.size() == 1);
        LogLens.clearSinks();
    }

    // ── FileSink ────────────────────────────────────────────────────────────
    static void fileSink() throws Exception {
        section("FileSink");
        File dir = Files.createTempDirectory("loglens-test").toFile();
        FileSink fs = new FileSink(dir, "app", 7);
        fs.write(Level.I, "APP_AUTH", "evt=LOGIN_OK uid=1 | 한글 메시지");
        fs.write(Level.E, "APP_NET", "evt=FAIL err=X");
        fs.close();

        File[] files = dir.listFiles();
        ok("파일이 하나 생김", files != null && files.length == 1);
        ok("날짜별 파일명", files[0].getName().matches("app-\\d{4}-\\d\\d-\\d\\d\\.log"));

        List<String> lines = Files.readAllLines(files[0].toPath(), StandardCharsets.UTF_8);
        ok("두 줄", lines.size() == 2);
        ok("UTF-8 한글 보존", lines.get(0).endsWith("| 한글 메시지"));
        ok("파일 싱크도 같은 접두사 규격",
                lines.get(1).matches("^\\d{4}-\\d\\d-\\d\\d \\d\\d:\\d\\d:\\d\\d\\.\\d{3} E/APP_NET: evt=FAIL err=X$"));

        for (File f : dir.listFiles()) f.delete();
        dir.delete();
    }

    // ── 하네스 ──────────────────────────────────────────────────────────────
    static void section(String name) {
        System.out.println("\n── " + name + " ──");
    }

    static void ok(String what, boolean cond) {
        if (cond) { passed++; }
        else { failed++; System.out.println("  FAIL  " + what); }
    }

    static void eq(String what, String expected, String actual) {
        if (expected.equals(actual)) { passed++; }
        else {
            failed++;
            System.out.println("  FAIL  " + what);
            System.out.println("        기대: " + expected);
            System.out.println("        실제: " + actual);
        }
    }

    static String repeat(String s, int n) {
        StringBuilder sb = new StringBuilder(s.length() * n);
        for (int i = 0; i < n; i++) sb.append(s);
        return sb.toString();
    }
}
