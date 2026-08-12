package io.loglens.demo;

import java.io.File;
import java.net.ConnectException;
import java.util.Random;

import io.loglens.core.FileSink;
import io.loglens.core.LogLens;
import io.loglens.core.ConsoleSink;
import io.loglens.sample.AppDomain;

/**
 * JVM 데모 앱 — 안드로이드 기기 없이 <b>진짜 emitter</b> 로 로그를 뿜는다.
 *
 * <pre>
 *   make demo          # 이 앱이 파일에 쓰고, 뷰어가 그 파일을 tail 한다
 * </pre>
 *
 * <p>합성 생성기(viewer/sources/synthetic.py)와 다른 점: 저건 파이썬이 문자열을
 * 흉내내는 것이고, 이건 <b>실제 라이브러리가 실제 계약대로</b> 찍는 것이다.
 * 즉 이 데모가 돌아간다는 건 emitter→viewer 파이프라인 전체가 돈다는 뜻이다.
 *
 * <p>call site 가 어떻게 생겼는지 보여주는 게 목적이므로, 코드는 일부러
 * 평범한 앱 코드처럼 썼다.
 */
public final class Demo {

    static final Random RND = new Random(7);

    public static void main(String[] args) throws Exception {
        // ── 앱 부트스트랩 (안드로이드에서는 LogLensAndroid.install(this) 한 줄) ──
        LogLens.init(true);                       // 앱이 빌드타입을 주입
        LogLens.addSink(new ConsoleSink());

        String out = arg(args, "--out", null);
        if (out != null) {
            File f = new File(out);
            LogLens.addSink(new FileSink(f.getParentFile() == null ? new File(".") : f.getParentFile(),
                    stripExt(f.getName()), 7));
        }

        int loops = Integer.parseInt(arg(args, "--loops", "40"));
        long pause = Long.parseLong(arg(args, "--pause-ms", "150"));

        for (int i = 0; i < loops; i++) {
            switch (RND.nextInt(5)) {
                case 0: login(); break;
                case 1: chat(); break;
                case 2: network(); break;
                case 3: upload(); break;
                default: legacyNoise(); break;
            }
            Thread.sleep(pause);
        }
        LogLens.clearSinks();
    }

    // ── 도메인별 call site 예시 ─────────────────────────────────────────────

    /** 퍼널: flowId 로 한 흐름을 묶는다 (기획서 §9-5 — 상관 ID 는 처음부터). */
    static void login() {
        String flowId = "f" + (1000 + RND.nextInt(9000));
        int uid = 100 + RND.nextInt(900);

        LogLens.i(AppDomain.AUTH, "LOGIN_START", "flowId", flowId, "uid", uid);
        LogLens.d(AppDomain.AUTH, "CREDENTIAL_CHECK", "flowId", flowId, "method", "password");

        if (RND.nextInt(10) < 3) {
            String reason = pick("WRONG_PW", "LOCKED", "EXPIRED");
            LogLens.w(AppDomain.AUTH, "LOGIN_FAIL",
                    "flowId", flowId, "uid", uid, "reason", reason,
                    "msg", "로그인 실패 — 사용자에게 안내함");
            return;
        }

        // 토큰은 절대 값으로 찍지 않는다. 그래도 실수로 넘기면 emitter 가 마스킹한다.
        LogLens.i(AppDomain.AUTH, "TOKEN_ISSUE",
                "flowId", flowId, "token", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0",
                "expiresIn", 3600, "authType", "oauth2");
        LogLens.d(AppDomain.AUTH, "PROFILE_FETCH", "flowId", flowId, "uid", uid);
        LogLens.i(AppDomain.AUTH, "LOGIN_OK", "flowId", flowId, "uid", uid, "msg", "로그인 성공");
    }

    static void chat() {
        int room = 1 + RND.nextInt(9);
        if (RND.nextInt(10) < 2) {
            LogLens.e(AppDomain.CHAT, "SEND_FAIL",
                    new IllegalStateException("socket already closed"),
                    "room", room, "retry", true);
            return;
        }
        LogLens.i(AppDomain.CHAT, "MSG_SEND_OK", "room", room, "len", 1 + RND.nextInt(200));
    }

    static void network() {
        if (RND.nextInt(10) < 3) {
            LogLens.e(AppDomain.NET, "REQUEST_FAIL",
                    new ConnectException("Failed to connect to api.example.test/10.0.0.1:443"),
                    "host", "api.example.test", "code", pick("500", "502", "408"));
            return;
        }
        LogLens.d(AppDomain.NET, "REQUEST_OK",
                "host", "api.example.test", "code", 200, "ms", 20 + RND.nextInt(880));
    }

    static void upload() {
        // 값에 공백이 든 파일명 — emitter 가 알아서 정화한다. 호출부는 신경 안 쓴다.
        String name = pick("보고서 최종.pdf", "a.png", "회의록 (수정).hwp");
        if (RND.nextInt(10) < 2) {
            LogLens.e(AppDomain.FILE_XFER, "UPLOAD_FAIL",
                    "name", name, "reason", "QUOTA_EXCEEDED", "size", 1024 + RND.nextInt(9_000_000));
            return;
        }
        LogLens.i(AppDomain.FILE_XFER, "UPLOAD_DONE",
                "name", name, "size", 1024 + RND.nextInt(9_000_000));
    }

    /**
     * 이관 전 레거시 로그. 뷰어는 이것도 버리지 않고 보여준다 —
     * 그래야 call site #1 부터 점진 도입이 가능하다 (기획서 §3).
     */
    static void legacyNoise() {
        System.out.println(io.loglens.core.LineFormat.timestamp()
                + " D/MainActivity: @@@@@ onResume, listSize=" + RND.nextInt(50));
    }

    // ── 유틸 ────────────────────────────────────────────────────────────────
    static String pick(String... xs) { return xs[RND.nextInt(xs.length)]; }

    static String arg(String[] args, String key, String def) {
        for (int i = 0; i < args.length - 1; i++) if (args[i].equals(key)) return args[i + 1];
        return def;
    }

    static String stripExt(String n) {
        int i = n.lastIndexOf('.');
        return i > 0 ? n.substring(0, i) : n;
    }
}
