package io.loglens.sample

import io.loglens.core.LogDomain

/**
 * **샘플** 도메인 (Kotlin 판).
 *
 * 라이브러리가 아니라 이 샘플 모듈에 있다는 점이 핵심입니다.
 * 실제 프로젝트는 이 파일을 복사해서 자기 도메인으로 바꿔 씁니다.
 *
 * ## 이름 규칙
 *
 * 도메인은 `[A-Z0-9_]+`. 이벤트는 대문자 SNAKE_CASE.
 * 성공과 실패는 접미사로 통일합니다 — `_OK` / `_FAIL`.
 * 뷰어의 성공률·실패 사유 집계가 이 규칙 위에서 돕니다.
 *
 * 규칙을 안 지키면 로그가 안 보이는 게 아니라 **분석에서 빠집니다.** 그게 지킬 이유입니다.
 *
 * ## 태그 길이
 *
 * `<접두사>_<도메인>` 이 23자를 넘지 않게 하세요. 넘으면 구형 기기에서
 * `adb shell setprop log.tag.<태그> VERBOSE` 로 레벨을 조절할 수 없습니다.
 */
enum class AppDomain : LogDomain {
    AUTH,
    CHAT,
    NET,
    FILE_XFER;

    override fun tag(): String = "$PREFIX$name"

    companion object {
        /** 프로젝트가 정하는 접두사. 뷰어 config.json 의 `prefix` 와 같아야 합니다. */
        const val PREFIX = "APP_"
    }
}
