package io.loglens.core

/** 로그 레벨. 문자 하나가 그대로 로그에 찍힙니다. */
enum class Level(@JvmField val c: Char) {
    V('V'), D('D'), I('I'), W('W'), E('E');

    /**
     * 릴리스에서 V/D 를 막습니다. I/W/E 는 항상 통과합니다.
     *
     * 라이브러리는 앱의 빌드 타입을 알 수 없으므로 [isDebug] 를 주입받습니다.
     */
    fun enabled(isDebug: Boolean): Boolean = isDebug || ordinal >= I.ordinal
}
