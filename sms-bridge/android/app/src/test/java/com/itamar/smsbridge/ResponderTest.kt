package com.itamar.smsbridge

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayOutputStream

class ResponderTest {

    private fun respond(method: String, build: (HttpUtil.Responder) -> Unit): String {
        val out = ByteArrayOutputStream()
        build(HttpUtil.Responder(out, method))
        return out.toString("UTF-8")
    }

    private fun bodyOf(raw: String): String {
        val split = raw.indexOf("\r\n\r\n")
        return raw.substring(split + 4)
    }

    private fun declaredLength(raw: String): Int =
        Regex("Content-Length: (\\d+)").find(raw)!!.groupValues[1].toInt()

    @Test
    fun `a GET response declares exactly as many bytes as it sends`() {
        val raw = respond("GET") { it.sendJson(200, """{"ok":true}""") }
        assertEquals("""{"ok":true}""", bodyOf(raw))
        assertEquals(declaredLength(raw), bodyOf(raw).toByteArray(Charsets.UTF_8).size)
    }

    @Test
    fun `a HEAD response keeps the length but sends no body`() {
        val raw = respond("HEAD") { it.sendJson(200, """{"ok":true}""") }
        assertEquals("", bodyOf(raw))
        assertEquals(11, declaredLength(raw))
    }

    @Test
    fun `head is matched regardless of case`() {
        assertEquals("", bodyOf(respond("head") { it.sendText(200, "hello") }))
        assertEquals("hello", bodyOf(respond("Get") { it.sendText(200, "hello") }))
    }

    /**
     * The regression this class exists for: a 400 used to declare a body and send none,
     * leaving the browser waiting for bytes that never came.
     */
    @Test
    fun `every error status sends the body it declares`() {
        for (status in listOf(400, 401, 404, 405, 429)) {
            val raw = respond("GET") { it.sendText(status, "Something went wrong") }
            assertTrue("status $status", raw.startsWith("HTTP/1.1 $status "))
            assertEquals("status $status", declaredLength(raw), bodyOf(raw).toByteArray().size)
            assertTrue("status $status", bodyOf(raw).isNotEmpty())
        }
    }

    @Test
    fun `multi-byte bodies are measured in bytes, not characters`() {
        val hebrew = "הרשאת קריאת SMS לא ניתנה"
        val raw = respond("GET") { it.sendText(200, hebrew) }
        assertEquals(hebrew, bodyOf(raw))
        // Declaring the character count here would truncate the response in the browser.
        assertEquals(hebrew.toByteArray(Charsets.UTF_8).size, declaredLength(raw))
        assertTrue(declaredLength(raw) > hebrew.length)
    }

    @Test
    fun `binary bodies pass through untouched`() {
        val out = ByteArrayOutputStream()
        val png = byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)
        HttpUtil.Responder(out, "GET").send(200, "image/png", png)
        val bytes = out.toByteArray()
        assertEquals(png.toList(), bytes.takeLast(png.size))
    }
}
