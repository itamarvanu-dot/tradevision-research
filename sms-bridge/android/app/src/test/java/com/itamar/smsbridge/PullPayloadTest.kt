package com.itamar.smsbridge

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PullPayloadTest {

    @Test
    fun `parses a pull with defaults`() {
        val r = PullPayload.parse(mapOf("t" to "pull", "req" to "abc"))!!
        assertEquals("abc", r.req)
        assertEquals(PullPayload.DEFAULT_MINUTES, r.minutes)
        assertEquals(PullPayload.DEFAULT_LIMIT, r.limit)
    }

    @Test
    fun `clamps hostile numbers`() {
        val r = PullPayload.parse(mapOf("t" to "pull", "req" to "a", "min" to "-5", "lim" to "999999"))!!
        assertEquals(0, r.minutes)
        assertEquals(PullPayload.MAX_LIMIT, r.limit)
    }

    @Test
    fun `ignores anything that is not a pull`() {
        assertNull(PullPayload.parse(mapOf("t" to "other", "req" to "a")))
        assertNull(PullPayload.parse(mapOf("t" to "pull")))
        assertNull(PullPayload.parse(mapOf("t" to "pull", "req" to "x".repeat(65))))
    }

    @Test
    fun `since honours the window, and zero means unbounded`() {
        val now = 10_000_000L
        assertEquals(now - 15 * 60_000L, PullPayload.since(PullPayload.Request("a", 15, 10), now))
        assertEquals(0L, PullPayload.since(PullPayload.Request("a", 0, 10), now))
    }

    @Test
    fun `builds the reply the iPhone page reads`() {
        val msg = SmsRepository.Message(7, "+972501234567", "אמא", "שלום", 123L, false)
        val json = PullPayload.build(PullPayload.Request("r1", 60, 10), listOf(msg), "Samsung SM-S918B", 81, 999L)
        val back = JSONObject(json.toString())
        assertEquals("r1", back.getString("req"))
        assertEquals("ok", back.getString("status"))
        assertEquals(81, back.getInt("battery"))
        val m = back.getJSONArray("messages").getJSONObject(0)
        assertEquals("+972501234567", m.getString("from"))
        assertEquals("אמא", m.getString("name"))
        assertEquals("שלום", m.getString("body"))
        assertEquals(false, m.getBoolean("read"))
    }

    @Test
    fun `unknown contact and battery serialise as null`() {
        val msg = SmsRepository.Message(1, "Bank", null, "x", 1L, true)
        val back = JSONObject(PullPayload.build(PullPayload.Request("r", 0, 1), listOf(msg), "d", null, 1L).toString())
        assert(back.isNull("battery"))
        assert(back.getJSONArray("messages").getJSONObject(0).isNull("name"))
    }
}
