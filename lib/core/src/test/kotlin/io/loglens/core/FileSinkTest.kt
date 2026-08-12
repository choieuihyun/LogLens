package io.loglens.core

import java.io.File
import java.nio.file.Files
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class FileSinkTest {

    private val dir: File = Files.createTempDirectory("loglens-test").toFile()

    @AfterTest
    fun cleanUp() {
        dir.listFiles()?.forEach { it.delete() }
        dir.delete()
    }

    @Test
    fun `날짜별 파일에 UTF-8 로 쓴다`() {
        FileSink(dir, "app", 7).use {
            it.write(Level.I, "APP_AUTH", "evt=LOGIN_OK uid=1 | 한글 메시지")
            it.write(Level.E, "APP_NET", "evt=FAIL err=X")
        }

        val files = dir.listFiles()!!
        assertEquals(1, files.size)
        assertTrue(files[0].name.matches(Regex("""app-\d{4}-\d\d-\d\d\.log""")), files[0].name)

        val lines = files[0].readLines()
        assertEquals(2, lines.size)
        assertTrue(lines[0].endsWith("| 한글 메시지"), lines[0])
        assertTrue(
            lines[1].matches(
                Regex("""^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} E/APP_NET: evt=FAIL err=X$""")
            ),
            lines[1],
        )
    }

    private inline fun FileSink.use(block: (FileSink) -> Unit) {
        try { block(this) } finally { close() }
    }
}
