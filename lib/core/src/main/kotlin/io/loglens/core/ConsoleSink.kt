package io.loglens.core

import java.io.PrintStream

/**
 * 표준 출력으로 내보냅니다. JVM 테스트, 데스크톱 데모, 뷰어와의 대조 검증에 씁니다.
 * 파일과 **같은 줄 앞부분 형식**을 쓰기 때문에 파서 하나로 둘 다 읽힙니다.
 */
class ConsoleSink @JvmOverloads constructor(
    private val out: PrintStream = System.out,
) : Sink {

    override fun write(level: Level, tag: String, body: String) {
        out.println(LineFormat.render(level, tag, body))
        out.flush()
    }
}
