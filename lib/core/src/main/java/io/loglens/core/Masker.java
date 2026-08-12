package io.loglens.core;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

/**
 * PII 마스킹 — <b>emitter 단</b>에서, <b>정확 키 매칭</b>으로.
 *
 * <p>emitter 단인 이유(기획서 §5): 수천 개의 call site 를 건드리지 않고 정책을 한 번에
 * 적용할 수 있다. 호출부는 마스킹을 신경 쓰지 않는다.
 *
 * <p>정확 매칭인 이유(기획서 §9-2, 실전 교훈): 부분 일치는 과잉 마스킹을 부른다.
 * {@code contains("auth")} 는 {@code authType} 까지 가려버려서, 정작 디버깅에 필요한
 * 멀쩡한 필드를 못 보게 만든다. 그러면 개발자가 마스킹을 우회하기 시작하고,
 * 그게 진짜 사고로 이어진다.
 */
public final class Masker {

    public static final String MASK = "***";

    /** 기본 민감 키 집합. 전부 소문자로 저장하고, 비교 시 키를 소문자화한다. */
    private static final Set<String> DEFAULT = Collections.unmodifiableSet(
            new HashSet<>(Arrays.asList(
                    "password", "passwd", "pwd", "pass",
                    "token", "access_token", "refresh_token", "id_token", "accesstoken",
                    "refreshtoken", "idtoken", "jwt", "bearer",
                    "secret", "apikey", "api_key", "authorization", "auth_header",
                    "cookie", "session_id", "sessionid", "credential", "credentials",
                    "ssn", "rrn", "phone", "tel", "mobile", "email", "mail",
                    "card", "card_no", "cardno", "pin", "cvv", "otp"
            )));

    private final Set<String> keys;

    public Masker() {
        this(DEFAULT);
    }

    public Masker(Set<String> sensitiveKeys) {
        Set<String> s = new HashSet<>();
        for (String k : sensitiveKeys) s.add(k.toLowerCase(Locale.ROOT));
        this.keys = Collections.unmodifiableSet(s);
    }

    /** 기본 집합에 프로젝트 고유 키를 더한 마스커. */
    public Masker plus(String... extra) {
        Set<String> s = new HashSet<>(keys);
        for (String k : extra) s.add(k.toLowerCase(Locale.ROOT));
        return new Masker(s);
    }

    public boolean isSensitive(String key) {
        return key != null && keys.contains(key.toLowerCase(Locale.ROOT));
    }

    /**
     * 마스킹된 값도 여전히 <b>공백 없는 토큰</b>이어야 한다 — 안 그러면
     * 개인정보를 가리려다 파서를 깨뜨리는 셈이 된다.
     */
    public String apply(String key, String sanitizedValue) {
        return isSensitive(key) ? MASK : sanitizedValue;
    }

    public static Set<String> defaultKeys() {
        return DEFAULT;
    }
}
