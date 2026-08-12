package io.loglens.sample;

import io.loglens.core.LogDomain;

/**
 * <b>샘플</b> 도메인 (Java 판).
 *
 * <p>자바가 대부분인 프로젝트는 이 파일을 복사해서 쓰면 됩니다.
 * 동작은 {@link AppDomain}(Kotlin 판)과 완전히 같습니다 — 둘 중 하나만 쓰세요.
 *
 * <p>호출부도 자바 그대로입니다:
 * <pre>{@code
 * LogLens.i(AppDomainJava.AUTH, "LOGIN_OK", "uid", uid, "msg", "로그인 성공");
 * }</pre>
 */
public enum AppDomainJava implements LogDomain {

    AUTH,
    CHAT,
    NET,
    FILE_XFER;

    /** 프로젝트가 정하는 접두사. 뷰어 config.json 의 {@code prefix} 와 같아야 합니다. */
    public static final String PREFIX = "APP_";

    @Override
    public String tag() {
        return PREFIX + name();
    }
}
