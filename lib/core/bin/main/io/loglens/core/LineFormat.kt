package io.loglens.core

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 파일과 콘솔로 내보낼 때 줄 앞에 붙이는 부분입니다.
 *
 * ```
 * 2026-08-12 11:23:45.678 I/APP_AUTH: evt=...
 * ```
 *
 * logcat 의 줄 앞부분은 안드로이드가 만듭니다(우리는 `-v threadtime` 으로 고정만 합니다).
 * 파일의 줄 앞부분은 **우리가 정하는** 것이라 연도를 넣었습니다 — 날짜별 파일을 나중에
 * 합쳐 볼 때 연도가 없으면 정렬이 애매해집니다.
 *
 * 뷰어 파서의 `filesink` 패턴과 한 쌍입니다. 여기를 바꾸면
 * docs/RECORD_FORMAT.md §3 과 parser.py 도 같이 바꿔야 합니다.
 */
object LineFormat {

    const val TS_PATTERN = "yyyy-MM-dd HH:mm:ss.SSS"

    // SimpleDateFormat 은 여러 스레드에서 같이 쓸 수 없습니다.
    //
    // ThreadLocal.withInitial() 을 쓰지 않는 이유: 자바 8 API 지만 안드로이드에서는
    // API 26 부터 존재합니다. minSdk 21 을 선언해 놓고 그걸 쓰면 API 21~25 기기에서
    // 클래스를 읽는 순간 NoSuchMethodError 로 죽습니다.
    private val FMT = object : ThreadLocal<SimpleDateFormat>() {
        override fun initialValue() = SimpleDateFormat(TS_PATTERN, Locale.US)
    }

    @JvmStatic
    fun render(level: Level, tag: String, body: String): String =
        "${timestamp()} ${level.c}/$tag: $body"

    @JvmStatic
    fun timestamp(): String = FMT.get()!!.format(Date())
}
