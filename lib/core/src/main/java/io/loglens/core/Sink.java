package io.loglens.core;

/**
 * 출력 대상. 플러그블 — logcat / 파일 / 크래시 리포터 브레드크럼 / 테스트용 메모리.
 *
 * <p>기획서 §5: 파일 싱크를 호스트 앱 유틸에 의존시키면 라이브러리가 그 앱에 묶인다.
 * 인터페이스로 뽑아 두면 core 는 안드로이드조차 모르는 순수 자바로 남는다.
 */
public interface Sink {

    /**
     * @param level 레벨
     * @param tag   logcat 태그 ({@code APP_AUTH})
     * @param body  이미 정화·마스킹·잘림 처리가 끝난 한 줄
     */
    void write(Level level, String tag, String body);

    /** 파일 핸들 등 정리. 기본은 no-op. */
    default void close() { }
}
