package io.loglens.core

/**
 * 도메인 — **앱이 정합니다.**
 *
 * 이 인터페이스 하나가 "어느 프로젝트에나 붙는다"의 전부입니다.
 * 도메인 목록은 프로젝트마다 다르기 때문에, 라이브러리 안에 enum 으로 박아 넣으면
 * 그 순간 다른 프로젝트에서 못 씁니다. 그래서 라이브러리는 도메인을 **모릅니다.**
 * 태그 문자열 하나만 받습니다.
 *
 * ```
 * enum class AppDomain : LogDomain {
 *     AUTH, CHAT, FILE_XFER, NET;
 *     override fun tag() = "APP_$name"
 * }
 * ```
 *
 * [tag] 가 돌려주는 값이 곧 logcat 태그이고, 곧 뷰어의 도메인 탭입니다.
 * 그래서 `<접두사>_<A-Z0-9_>+` 규칙을 지켜야 합니다. 안 지켜도 로그가 사라지지는 않고,
 * 뷰어가 형식에 맞는 레코드로 인식하지 못해서 일반 로그로 보여줄 뿐입니다.
 */
fun interface LogDomain {

    /** logcat 태그. `<접두사>_<도메인>` 형태여야 합니다. 예: `APP_AUTH` */
    fun tag(): String
}
