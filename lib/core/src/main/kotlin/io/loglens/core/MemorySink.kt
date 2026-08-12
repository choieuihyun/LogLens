package io.loglens.core

import java.util.Collections

/** 테스트용. 찍힌 줄을 그대로 들고 있습니다. */
class MemorySink : Sink {

    private val _lines = Collections.synchronizedList(mutableListOf<String>())
    private val _bodies = Collections.synchronizedList(mutableListOf<String>())

    override fun write(level: Level, tag: String, body: String) {
        _bodies.add(body)
        _lines.add(LineFormat.render(level, tag, body))
    }

    /** 줄 앞부분까지 붙은 완성된 줄들. */
    fun lines(): List<String> = ArrayList(_lines)

    /** 본문만 (형식의 핵심 부분). */
    fun bodies(): List<String> = ArrayList(_bodies)

    fun lastBody(): String? = _bodies.lastOrNull()

    fun clear() {
        _lines.clear()
        _bodies.clear()
    }

    val size: Int get() = _bodies.size
}
