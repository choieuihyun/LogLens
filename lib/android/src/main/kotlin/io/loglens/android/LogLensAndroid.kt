package io.loglens.android

import android.content.Context
import android.content.pm.ApplicationInfo
import io.loglens.core.FileSink
import io.loglens.core.LogLens
import java.io.File

/**
 * 안드로이드에서 한 줄로 설정을 끝냅니다.
 *
 * ```
 * class App : Application() {
 *     override fun onCreate() {
 *         super.onCreate()
 *         LogLensAndroid.install(this)          // logcat 만
 *         // LogLensAndroid.install(this, true) // + 날짜별 파일
 *     }
 * }
 * ```
 *
 * ## 왜 BuildConfig.DEBUG 를 안 쓰는가
 *
 * 라이브러리 모듈의 `BuildConfig.DEBUG` 는 **그 라이브러리의** 빌드 타입입니다.
 * 앱을 release 로 빌드해도 라이브러리 쪽이 true 로 남는 조합이 실제로 있습니다.
 * 그러면 릴리스 앱에서 V/D 로그가 전부 새어 나갑니다.
 *
 * 그래서 앱의 [ApplicationInfo.FLAG_DEBUGGABLE] 을 실행 중에 확인합니다.
 * 이건 언제나 **앱**의 상태입니다.
 */
object LogLensAndroid {

    @JvmStatic
    @JvmOverloads
    fun install(ctx: Context, withFileSink: Boolean = false) {
        LogLens.init(isDebuggable(ctx))
        LogLens.addSink(LogcatSink())
        if (withFileSink) {
            LogLens.addSink(FileSink(File(ctx.filesDir, "loglens"), "app", 7))
        }
    }

    /** 앱이 디버그 빌드인지. 라이브러리의 빌드 타입과 무관하게 언제나 정확합니다. */
    @JvmStatic
    fun isDebuggable(ctx: Context): Boolean =
        (ctx.applicationInfo?.flags ?: 0) and ApplicationInfo.FLAG_DEBUGGABLE != 0
}
