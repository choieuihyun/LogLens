package io.loglens.core

/** 로그 레벨. 문자 하나가 그대로 로그에 찍힙니다. */
enum class Level(@JvmField val c: Char) {
    V('V'), D('D'), I('I'), W('W'), E('E');

    /**
     * 기본 정책([ReleasePolicy.SILENT])에서 이 레벨이 나가는가 — 디버그면 전부, 릴리스면 아무것도.
     *
     * 예전에는 릴리스에서도 I/W/E 를 통과시켰습니다. 지금은 릴리스 출력을 앱이 [ReleasePolicy] 로
     * 직접 고르므로, 레벨만으로는 답할 수 없습니다. [LogLens] 도 더 이상 이 메서드를 쓰지 않습니다.
     * (docs/DECISIONS.md D24)
     */
    @Deprecated("릴리스 출력은 ReleasePolicy 가 정합니다.", ReplaceWith("isDebug"))
    fun enabled(isDebug: Boolean): Boolean = isDebug
}
