package io.loglens.core

/**
 * 로그를 실제로 내보내는 곳. logcat, 파일, 크래시 리포터, 테스트용 메모리 등.
 *
 * 파일 저장을 호스트 앱의 유틸에 의존시키면 라이브러리가 그 앱에 묶입니다.
 * 인터페이스로 빼 두면 core 는 안드로이드조차 모르는 순수 Kotlin 으로 남습니다.
 */
interface Sink {

    /**
     * @param level 레벨
     * @param tag   logcat 태그 (`APP_AUTH`)
     * @param body  값 정리·마스킹·길이 자르기가 이미 끝난 한 줄
     */
    fun write(level: Level, tag: String, body: String)

    /**
     * 전역 레벨 게이팅이 막은 로그라도 이 출력 대상은 받고 싶은가.
     *
     * 릴리스 빌드에서는 V/D 가 막힙니다. 그런데 현장에서 "채팅만 상세 로그 좀 보내주세요"
     * 같은 요청을 받을 때가 있습니다. 앱을 다시 빌드하지 않고 켜려면 출력 대상이
     * 스스로 판단할 수 있어야 합니다.
     *
     * logcat 출력은 이걸 `Log.isLoggable(tag, level)` 로 구현합니다. 그러면
     * `adb shell setprop log.tag.UC_CHAT VERBOSE` 한 줄로 그 도메인만 열립니다.
     * 태그가 곧 도메인이라서 도메인 단위 제어가 공짜로 따라옵니다.
     *
     * 기본값은 false — 아무것도 바꾸지 않습니다.
     */
    fun isForcedOn(level: Level, tag: String): Boolean = false

    /** 파일 핸들 등을 정리합니다. 기본은 아무것도 안 합니다. */
    fun close() {}
}
