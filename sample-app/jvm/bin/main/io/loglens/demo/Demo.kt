package io.loglens.demo

import io.loglens.core.ConsoleSink
import io.loglens.core.FileSink
import io.loglens.core.LineFormat
import io.loglens.core.LogLens
import io.loglens.sample.AppDomain
import java.io.File
import java.net.ConnectException
import kotlin.random.Random

/**
 * 기기 없이 **진짜 라이브러리**로 로그를 뿜는 데모입니다.
 *
 * 뷰어의 가짜 로그 생성기와 다른 점: 저건 파이썬이 문자열을 흉내내는 것이고,
 * 이건 실제 라이브러리가 실제 형식대로 찍는 것입니다.
 * 즉 이 데모가 돌아간다는 건 라이브러리→뷰어 전 구간이 돈다는 뜻입니다.
 *
 * 호출부가 어떻게 생겼는지 보여주는 게 목적이라 일부러 평범한 앱 코드처럼 썼습니다.
 * Kotlin 호출부는 여기, Java 호출부는 [JavaCallSite] 에 있습니다.
 */
private val rnd = Random(7)

fun main(args: Array<String>) {
    // 앱 시작 부분 (안드로이드에서는 LogLensAndroid.install(this) 한 줄)
    LogLens.init(true)
    LogLens.addSink(ConsoleSink())

    arg(args, "--out")?.let { out ->
        val f = File(out)
        LogLens.addSink(FileSink(f.parentFile ?: File("."), f.nameWithoutExtension, 7))
    }

    val loops = arg(args, "--loops")?.toInt() ?: 40
    val pause = arg(args, "--pause-ms")?.toLong() ?: 150L

    repeat(loops) {
        when (rnd.nextInt(6)) {
            0 -> login()
            1 -> chat()
            2 -> network()
            3 -> upload()
            4 -> JavaCallSite.javaStyleCall()   // 자바 호출부도 섞어서
            else -> legacyNoise()
        }
        Thread.sleep(pause)
    }
    LogLens.clearSinks()
}

// ── 도메인별 호출부 예시 (Kotlin — Pair 방식) ───────────────────────────────

/** 흐름을 flowId 로 묶습니다. 이게 있어야 단계별 이탈을 볼 수 있습니다. */
private fun login() {
    val flowId = "f${1000 + rnd.nextInt(9000)}"
    val uid = 100 + rnd.nextInt(900)

    LogLens.i(AppDomain.AUTH, "LOGIN_START", "flowId" to flowId, "uid" to uid)
    LogLens.d(AppDomain.AUTH, "CREDENTIAL_CHECK", "flowId" to flowId, "method" to "password")

    if (rnd.nextInt(10) < 3) {
        LogLens.w(
            AppDomain.AUTH, "LOGIN_FAIL",
            "flowId" to flowId,
            "uid" to uid,
            "reason" to pick("WRONG_PW", "LOCKED", "EXPIRED"),
            "msg" to "로그인 실패 — 사용자에게 안내함",
        )
        return
    }

    // 토큰은 값으로 찍지 않습니다. 실수로 넘겨도 라이브러리가 가려 줍니다.
    LogLens.i(
        AppDomain.AUTH, "TOKEN_ISSUE",
        "flowId" to flowId,
        "token" to "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0",
        "expiresIn" to 3600,
        "authType" to "oauth2",
    )
    LogLens.d(AppDomain.AUTH, "PROFILE_FETCH", "flowId" to flowId, "uid" to uid)
    LogLens.i(AppDomain.AUTH, "LOGIN_OK", "flowId" to flowId, "uid" to uid, "msg" to "로그인 성공")
}

private fun chat() {
    val room = 1 + rnd.nextInt(9)
    if (rnd.nextInt(10) < 2) {
        LogLens.e(
            AppDomain.CHAT, "SEND_FAIL",
            IllegalStateException("socket already closed"),
            "room" to room, "retry" to true,
        )
        return
    }
    LogLens.i(AppDomain.CHAT, "MSG_SEND_OK", "room" to room, "len" to (1 + rnd.nextInt(200)))
}

private fun network() {
    if (rnd.nextInt(10) < 3) {
        LogLens.e(
            AppDomain.NET, "REQUEST_FAIL",
            ConnectException("Failed to connect to api.example.test/10.0.0.1:443"),
            "host" to "api.example.test", "code" to pick("500", "502", "408"),
        )
        return
    }
    LogLens.d(
        AppDomain.NET, "REQUEST_OK",
        "host" to "api.example.test", "code" to 200, "ms" to (20 + rnd.nextInt(880)),
    )
}

private fun upload() {
    // 파일 이름에 공백이 있어도 라이브러리가 알아서 정리합니다. 호출부는 신경 안 씁니다.
    val name = pick("보고서 최종.pdf", "a.png", "회의록 (수정).hwp")
    val size = 1024 + rnd.nextInt(9_000_000)
    if (rnd.nextInt(10) < 2) {
        LogLens.e(
            AppDomain.FILE_XFER, "UPLOAD_FAIL",
            "name" to name, "reason" to "QUOTA_EXCEEDED", "size" to size,
        )
        return
    }
    LogLens.i(AppDomain.FILE_XFER, "UPLOAD_DONE", "name" to name, "size" to size)
}

/**
 * 아직 안 옮긴 예전 로그. 뷰어는 이것도 버리지 않고 보여줍니다 —
 * 그래야 라이브러리를 안 쓰는 앱에도 붙일 수 있습니다.
 */
private fun legacyNoise() {
    println("${LineFormat.timestamp()} D/MainActivity: @@@@@ onResume, listSize=${rnd.nextInt(50)}")
}

private fun pick(vararg xs: String) = xs[rnd.nextInt(xs.size)]

private fun arg(args: Array<String>, key: String): String? {
    val i = args.indexOf(key)
    return if (i >= 0 && i + 1 < args.size) args[i + 1] else null
}
