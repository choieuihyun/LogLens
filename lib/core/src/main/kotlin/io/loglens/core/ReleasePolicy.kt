package io.loglens.core

/**
 * 릴리스(디버그가 아닌) 빌드에서 무엇을 내보낼지.
 *
 * 기본은 [SILENT] — **아무것도 내보내지 않습니다.** 릴리스 기기의 logcat 에 앱 내부 사정이
 * 남지 않게 하려는 것이고, 초기화를 깜빡해도 새지 않는 방향입니다.
 *
 * 릴리스에서도 경고나 에러를 받아 봐야 하는 앱은 초기화할 때 **직접 골라서** 엽니다.
 *
 * ```
 * LogLens.init(isDebug, ReleasePolicy.WARN_AND_ABOVE)                       // 릴리스에서 W, E 만
 * LogLens.init(isDebug, ReleasePolicy.SILENT.withRuntimeSwitch())           // 평소엔 조용, 필요할 때 기기에서 켬
 * LogLens.init(isDebug, ReleasePolicy.INFO_AND_ABOVE.withRuntimeSwitch())   // 예전 동작
 * ```
 *
 * 무엇을 고르든 **원문([LogLens.payload])은 릴리스에서 나가지 않습니다.** 요청·응답 본문에는
 * 개인정보가 섞일 수 있어서, 여는 길 자체를 두지 않았습니다.
 *
 * 디버그 빌드에서는 이 값과 상관없이 전부 나갑니다.
 */
class ReleasePolicy private constructor(
    private val minLevel: Level?,
    /** 출력 대상이 런타임으로 켜 달라는 것을 들어줄지. [withRuntimeSwitch] 참고. */
    @JvmField val runtimeSwitch: Boolean,
) {

    /** 이 레벨이 릴리스에서 그냥 나가는가 (런타임 스위치와 무관하게). */
    fun passes(level: Level): Boolean = minLevel != null && level.ordinal >= minLevel.ordinal

    /** 릴리스에서 나갈 길이 하나도 없는가. */
    fun isSilent(): Boolean = minLevel == null && !runtimeSwitch

    /**
     * 출력 대상이 막힌 로그를 다시 열 수 있게 합니다 ([Sink.isForcedOn]).
     *
     * logcat 출력은 `adb shell setprop log.tag.<태그> VERBOSE` 로 도메인 하나를 엽니다.
     * 현장에서 "채팅만 상세 로그 보내 주세요" 같은 요청을 앱을 다시 빌드하지 않고 받으려는 것입니다.
     * 대신 adb 를 붙일 수 있는 사람이면 누구나 켤 수 있다는 뜻이기도 합니다.
     */
    fun withRuntimeSwitch(): ReleasePolicy = ReleasePolicy(minLevel, true)

    override fun toString(): String =
        (if (minLevel == null) "SILENT" else "${minLevel.name}+") + (if (runtimeSwitch) "+switch" else "")

    companion object {
        /** 릴리스에서는 아무것도 내보내지 않습니다. 기본값. */
        @JvmField val SILENT = ReleasePolicy(null, false)

        /** 릴리스에서 I, W, E 를 내보냅니다. */
        @JvmField val INFO_AND_ABOVE = ReleasePolicy(Level.I, false)

        /** 릴리스에서 W, E 를 내보냅니다. */
        @JvmField val WARN_AND_ABOVE = ReleasePolicy(Level.W, false)

        /** 릴리스에서 E 만 내보냅니다. */
        @JvmField val ERROR_ONLY = ReleasePolicy(Level.E, false)
    }
}
