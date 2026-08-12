package io.loglens.core;

/**
 * 도메인 — <b>앱이 공급한다.</b>
 *
 * <p>이 인터페이스가 "어느 프로젝트에나 붙는다"의 전부다. 도메인 목록은 프로젝트의
 * 정체성이라 앱마다 다르다. 라이브러리에 enum 으로 박으면 그 순간 재사용이 끝난다.
 * 그래서 라이브러리는 도메인을 <b>모른다</b>. 태그 문자열 하나만 받는다.
 *
 * <pre>{@code
 * public enum AppDomain implements LogDomain {
 *     AUTH, CHAT, FILE_XFER, NET;
 *     @Override public String tag() { return "APP_" + name(); }
 * }
 * }</pre>
 *
 * <p>{@link #tag()} 이 돌려주는 값이 곧 logcat 태그이고, 곧 뷰어의 도메인 탭이다.
 * 그래서 {@code <PREFIX>_<A-Z0-9_>+} 규칙을 지켜야 한다 — 지키지 않으면 뷰어가
 * 구조화 레코드로 인식하지 못하고 그냥 일반 로그로 보여준다(깨지지는 않는다).
 */
public interface LogDomain {

    /** logcat 태그. {@code <PREFIX>_<DOMAIN>} 형태여야 한다. 예: {@code APP_AUTH} */
    String tag();
}
