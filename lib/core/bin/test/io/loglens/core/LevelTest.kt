package io.loglens.core

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class LevelTest {

    @Test
    fun `기본 정책은 릴리스에서 어떤 레벨도 통과시키지 않는다`() {
        for (level in Level.values()) assertFalse(ReleasePolicy.SILENT.passes(level), level.name)
        assertTrue(ReleasePolicy.SILENT.isSilent())
    }

    @Test
    fun `정책으로 연 레벨부터 통과한다`() {
        assertFalse(ReleasePolicy.INFO_AND_ABOVE.passes(Level.D))
        assertTrue(ReleasePolicy.INFO_AND_ABOVE.passes(Level.I))
        assertFalse(ReleasePolicy.WARN_AND_ABOVE.passes(Level.I))
        assertTrue(ReleasePolicy.WARN_AND_ABOVE.passes(Level.W))
        assertFalse(ReleasePolicy.ERROR_ONLY.passes(Level.W))
        assertTrue(ReleasePolicy.ERROR_ONLY.passes(Level.E))
    }

    @Test
    fun `런타임 스위치는 따로 켜야 하고 레벨 통과와는 별개다`() {
        assertFalse(ReleasePolicy.INFO_AND_ABOVE.runtimeSwitch)
        val p = ReleasePolicy.SILENT.withRuntimeSwitch()
        assertTrue(p.runtimeSwitch)
        assertFalse(p.passes(Level.E), "스위치를 켰다고 레벨이 그냥 통과하지는 않는다")
        assertFalse(p.isSilent())
        assertFalse(ReleasePolicy.SILENT.runtimeSwitch, "기본값 자체는 바뀌지 않는다")
    }
}
