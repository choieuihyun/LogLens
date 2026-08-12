package io.loglens.core

import java.util.Locale

/**
 * 개인정보 마스킹 — **로그를 찍는 쪽에서**, **키 이름이 정확히 일치할 때만.**
 *
 * 찍는 쪽에서 하는 이유: 호출부 수천 곳을 건드리지 않고 정책을 한 번에 적용할 수 있습니다.
 * 호출부는 마스킹을 신경 쓰지 않습니다.
 *
 * 정확히 일치할 때만 가리는 이유: 일부만 맞아도 가리면 멀쩡한 필드까지 사라집니다.
 * `contains("auth")` 로 하면 `authType` 까지 가려져서, 정작 디버깅에 필요한 값을
 * 못 보게 됩니다. 그러면 개발자가 마스킹을 우회하기 시작하고, 그게 진짜 사고로 이어집니다.
 */
class Masker private constructor(private val keys: Set<String>) {

    constructor() : this(DEFAULT)

    /** 프로젝트 고유 키를 기본 집합에 더한 마스커를 만듭니다. */
    fun plus(vararg extra: String): Masker =
        Masker(keys + extra.map { it.lowercase(Locale.ROOT) })

    fun isSensitive(key: String?): Boolean =
        key != null && key.lowercase(Locale.ROOT) in keys

    /**
     * 가려진 값도 여전히 **공백 없는 한 덩어리**여야 합니다.
     * 개인정보를 가리려다 파서를 깨뜨리면 안 되니까요.
     */
    fun apply(key: String?, sanitizedValue: String): String =
        if (isSensitive(key)) MASK else sanitizedValue

    companion object {
        const val MASK = "***"

        /** 기본 민감 키 목록. 전부 소문자로 두고, 비교할 때 키를 소문자로 바꿉니다. */
        @JvmStatic
        val DEFAULT: Set<String> = setOf(
            "password", "passwd", "pwd", "pass",
            "token", "access_token", "refresh_token", "id_token", "accesstoken",
            "refreshtoken", "idtoken", "jwt", "bearer",
            "secret", "apikey", "api_key", "authorization", "auth_header",
            "cookie", "session_id", "sessionid", "credential", "credentials",
            "ssn", "rrn", "phone", "tel", "mobile", "email", "mail",
            "card", "card_no", "cardno", "pin", "cvv", "otp",
        )

        /** 직접 고른 키 목록으로 마스커를 만듭니다. */
        @JvmStatic
        fun of(sensitiveKeys: Set<String>): Masker =
            Masker(sensitiveKeys.map { it.lowercase(Locale.ROOT) }.toSet())
    }
}
