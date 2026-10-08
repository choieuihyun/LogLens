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
     * 릴리스에서 막힌 로그라도 이 출력 대상은 받고 싶은가.
     *
     * **앱이 [ReleasePolicy.withRuntimeSwitch] 로 허용했을 때만 물어봅니다.** 기본 정책에서는
     * 무엇을 돌려주든 릴리스에서 아무것도 나가지 않습니다. 원문([LogLens.payload])에는 어떤
     * 경우에도 적용되지 않습니다.
     *
     * 현장에서 "채팅만 상세 로그 좀 보내주세요" 같은 요청을 받을 때, 앱을 다시 빌드하지 않고
     * 켜려는 용도입니다. logcat 출력은 이걸 `Log.isLoggable(tag, level)` 로 구현합니다. 그러면
     * `adb shell setprop log.tag.UC_CHAT VERBOSE` 한 줄로 그 도메인만 열립니다.
     *
     * 기본값은 false — 아무것도 바꾸지 않습니다.
     */
    fun isForcedOn(level: Level, tag: String): Boolean = false

    /**
     * 원문(요청·응답 본문)을 받을 것인가. 기본은 받지 않습니다.
     *
     * 원문에는 개인정보가 섞여 있을 수 있습니다. 파일처럼 기기에 오래 남는 출력 대상은
     * 스스로 받겠다고 밝힐 때만 받습니다. [LogLens.payload] 가 이 값을 봅니다.
     */
    fun acceptsPayload(): Boolean = false

    /** 파일 핸들 등을 정리합니다. 기본은 아무것도 안 합니다. */
    fun close() {}
}
