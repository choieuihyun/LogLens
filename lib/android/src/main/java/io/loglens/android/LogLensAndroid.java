package io.loglens.android;

import android.content.Context;
import android.content.pm.ApplicationInfo;

import java.io.File;

import io.loglens.core.FileSink;
import io.loglens.core.LogLens;

/**
 * 안드로이드 부트스트랩 한 줄.
 *
 * <pre>{@code
 * public class App extends Application {
 *     @Override public void onCreate() {
 *         super.onCreate();
 *         LogLensAndroid.install(this);          // logcat 만
 *         // LogLensAndroid.install(this, true); // + 날짜별 파일
 *     }
 * }
 * }</pre>
 *
 * <h2>왜 {@code BuildConfig.DEBUG} 를 안 쓰는가</h2>
 * 라이브러리 모듈의 {@code BuildConfig.DEBUG} 는 <b>그 라이브러리의</b> 빌드타입이다.
 * 앱이 release 로 빌드돼도 라이브러리 쪽이 true 로 남는 조합이 실제로 존재한다.
 * 그러면 릴리스 앱에서 V/D 로그가 통째로 새어나간다. 그래서 앱의
 * {@link ApplicationInfo#FLAG_DEBUGGABLE} 를 런타임에 확인한다 —
 * 이건 항상 <b>앱</b>의 상태다.
 */
public final class LogLensAndroid {

    private LogLensAndroid() {}

    public static void install(Context ctx) {
        install(ctx, false);
    }

    public static void install(Context ctx, boolean withFileSink) {
        LogLens.init(isDebuggable(ctx));
        LogLens.addSink(new LogcatSink());
        if (withFileSink) {
            File dir = new File(ctx.getFilesDir(), "loglens");
            LogLens.addSink(new FileSink(dir, "app", 7));
        }
    }

    /** 앱이 디버그 빌드인가. 라이브러리 빌드타입과 무관하게 항상 정확하다. */
    public static boolean isDebuggable(Context ctx) {
        ApplicationInfo ai = ctx.getApplicationInfo();
        return ai != null && (ai.flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0;
    }
}
