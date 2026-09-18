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

    /** 파일 핸들 등을 정리합니다. 기본은 아무것도 안 합니다. */
    fun close() {}
}
