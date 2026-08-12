package io.loglens.core

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class LevelTest {

    @Test fun `릴리스에서 V 는 막힌다`() = assertFalse(Level.V.enabled(false))
    @Test fun `릴리스에서 D 는 막힌다`() = assertFalse(Level.D.enabled(false))
    @Test fun `릴리스에서 I 는 통과`() = assertTrue(Level.I.enabled(false))
    @Test fun `릴리스에서 W 는 통과`() = assertTrue(Level.W.enabled(false))
    @Test fun `릴리스에서 E 는 통과`() = assertTrue(Level.E.enabled(false))
    @Test fun `디버그에서는 V 도 통과`() = assertTrue(Level.V.enabled(true))
}
