package io.loglens.core

import java.io.BufferedWriter
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.OutputStreamWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 날짜별 파일로 남깁니다. 순수 Kotlin 이라 호스트 앱의 파일 유틸에 의존하지 않습니다.
 *
 * logcat 은 링버퍼라 금방 밀립니다. 재현이 어려운 버그는 파일에 남아 있어야 잡힙니다.
 * 뷰어는 `--source file` 로 이 파일을 그대로 재생할 수 있습니다 — 같은 줄 형식이니까요.
 *
 * @param dir      로그를 둘 디렉터리
 * @param prefix   파일 이름 앞부분 → `app-2026-08-12.log`
 * @param keepDays 이 일수보다 오래된 파일은 지웁니다 (0 이면 안 지웁니다)
 */
class FileSink @JvmOverloads constructor(
    private val dir: File,
    private val prefix: String = "app",
    private val keepDays: Int = 7,
) : Sink {

    private var currentDay: String? = null
    private var writer: BufferedWriter? = null

    init {
        dir.mkdirs()
        purgeOld()
    }

    @Synchronized
    override fun write(level: Level, tag: String, body: String) {
        try {
            roll()
            val w = writer ?: return
            w.write(LineFormat.render(level, tag, body))
            w.newLine()
            w.flush()
        } catch (ignored: IOException) {
            // 파일에 못 쓴다고 앱이 죽으면 안 됩니다.
        }
    }

    private fun roll() {
        val day = DAY.get()!!.format(Date())
        if (day == currentDay && writer != null) return
        closeQuietly()
        currentDay = day
        val f = File(dir, "$prefix-$day.log")
        writer = BufferedWriter(OutputStreamWriter(FileOutputStream(f, true), Charsets.UTF_8))
        purgeOld()
    }

    private fun purgeOld() {
        if (keepDays <= 0) return
        val files = dir.listFiles { _, name -> name.startsWith("$prefix-") && name.endsWith(".log") }
            ?: return
        val cutoff = System.currentTimeMillis() - keepDays * 86_400_000L
        files.filter { it.lastModified() < cutoff }.forEach { it.delete() }
    }

    @Synchronized
    override fun close() = closeQuietly()

    private fun closeQuietly() {
        try {
            writer?.close()
        } catch (ignored: IOException) {
        }
        writer = null
    }

    private companion object {
        // withInitial() 은 안드로이드 API 26+ 입니다 (LineFormat 주석 참고). minSdk 21 을 지킵니다.
        val DAY = object : ThreadLocal<SimpleDateFormat>() {
            override fun initialValue() = SimpleDateFormat("yyyy-MM-dd", Locale.US)
        }
    }
}
