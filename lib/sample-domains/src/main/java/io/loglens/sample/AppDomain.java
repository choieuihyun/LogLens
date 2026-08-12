package io.loglens.sample;

import io.loglens.core.LogDomain;

/**
 * <b>샘플</b> 도메인. 라이브러리에 들어 있지 않고 여기 샘플 모듈에 있다는 점이 핵심이다.
 *
 * <p>실제 프로젝트는 이 파일을 복사해서 자기 도메인으로 갈아끼운다.
 * 도메인 목록은 프로젝트의 정체성이지 라이브러리의 것이 아니다.
 *
 * <h2>이름 거버넌스 (기획서 §9-4)</h2>
 * 도메인은 {@code [A-Z0-9_]+}. 이벤트는 대문자 SNAKE_CASE.
 * 성공/실패는 접미사로 통일한다 — {@code _OK} / {@code _FAIL}.
 * 뷰어 대시보드의 성공률·실패사유 집계가 이 규칙 위에서 돈다.
 * 규칙을 안 지키면 로그가 안 보이는 게 아니라 <b>분석에서 빠진다</b>. 그게 채택 유인이다.
 */
public enum AppDomain implements LogDomain {

    AUTH,
    CHAT,
    NET,
    FILE_XFER;

    /** 프로젝트가 정하는 접두사. 뷰어 config.json 의 {@code prefix} 와 같아야 한다. */
    public static final String PREFIX = "APP";

    @Override
    public String tag() {
        return PREFIX + "_" + name();
    }
}
