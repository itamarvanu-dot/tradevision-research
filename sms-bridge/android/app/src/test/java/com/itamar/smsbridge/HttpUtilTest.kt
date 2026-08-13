package com.itamar.smsbridge

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.IOException

class HttpUtilTest {

    private fun request(raw: String) =
        HttpUtil.readRequest(ByteArrayInputStream(raw.toByteArray(Charsets.UTF_8)))

    @Test
    fun `parses method path and headers`() {
        val parsed = request(
            "GET /api/messages HTTP/1.1\r\n" +
                "Host: 192.168.1.20:8080\r\n" +
                "X-Bridge-Token: abc123\r\n" +
                "\r\n"
        )!!
        assertEquals("GET", parsed.method)
        assertEquals("/api/messages", parsed.path)
        assertEquals("abc123", parsed.headers["x-bridge-token"])
        assertEquals("192.168.1.20:8080", parsed.headers["host"])
    }

    @Test
    fun `splits query string off the path`() {
        val parsed = request("GET /api/messages?limit=50&q=%D7%A7%D7%95%D7%93 HTTP/1.1\r\n\r\n")!!
        assertEquals("/api/messages", parsed.path)
        assertEquals("50", parsed.query["limit"])
        assertEquals("קוד", parsed.query["q"])
    }

    @Test
    fun `header names are matched case insensitively`() {
        val parsed = request("GET / HTTP/1.1\r\nx-BRIDGE-Token: t\r\n\r\n")!!
        assertEquals("t", parsed.headers["x-bridge-token"])
    }

    @Test
    fun `returns null on an empty or malformed request line`() {
        assertNull(request(""))
        assertNull(request("GARBAGE\r\n\r\n"))
    }

    @Test(expected = IOException::class)
    fun `rejects an absurdly long header line`() {
        request("GET /" + "a".repeat(HttpUtil.MAX_HEADER_BYTES + 10) + " HTTP/1.1\r\n\r\n")
    }

    @Test
    fun `token comes from the header, then token, then t`() {
        val fromHeader = request("GET /api/info?token=q HTTP/1.1\r\nX-Bridge-Token: h\r\n\r\n")!!
        assertEquals("h", HttpUtil.tokenFrom(fromHeader))

        val fromQuery = request("GET /api/info?token=q HTTP/1.1\r\n\r\n")!!
        assertEquals("q", HttpUtil.tokenFrom(fromQuery))

        val fromShort = request("GET /api/info?t=s HTTP/1.1\r\n\r\n")!!
        assertEquals("s", HttpUtil.tokenFrom(fromShort))

        val none = request("GET /api/info HTTP/1.1\r\n\r\n")!!
        assertEquals("", HttpUtil.tokenFrom(none))
    }

    @Test
    fun `query parsing survives odd input`() {
        val q = HttpUtil.parseQuery("a=1&&flag&b=%zz&c=x%20y")
        assertEquals("1", q["a"])
        assertEquals("", q["flag"])
        assertEquals("x y", q["c"])
        assertFalse(q.containsKey("b")) // malformed escape is dropped, not fatal
    }

    @Test
    fun `token comparison rejects mismatches including the empty token`() {
        assertTrue(HttpUtil.constantTimeEquals("abcdef", "abcdef"))
        assertFalse(HttpUtil.constantTimeEquals("abcdef", "abcdeg"))
        assertFalse(HttpUtil.constantTimeEquals("abc", "abcdef"))
        // An unset token must never authenticate an empty request.
        assertFalse(HttpUtil.constantTimeEquals("", ""))
    }

    @Test
    fun `static paths cannot escape the assets directory`() {
        assertEquals("index.html", HttpUtil.assetNameFor("/"))
        assertEquals("index.html", HttpUtil.assetNameFor("/index.html"))
        assertEquals("icon.svg", HttpUtil.assetNameFor("/icon.svg"))

        assertNull(HttpUtil.assetNameFor("/../AndroidManifest.xml"))
        assertNull(HttpUtil.assetNameFor("/sub/dir.html"))
        assertNull(HttpUtil.assetNameFor("/..%2Fsecret".replace("%2F", "/")))
        assertNull(HttpUtil.assetNameFor("/.hidden"))
    }

    @Test
    fun `content types cover what the UI actually loads`() {
        assertEquals("text/html; charset=utf-8", HttpUtil.contentTypeFor("index.html"))
        assertEquals("image/svg+xml", HttpUtil.contentTypeFor("icon.svg"))
        assertEquals(
            "application/manifest+json; charset=utf-8",
            HttpUtil.contentTypeFor("manifest.webmanifest"),
        )
        assertEquals("application/octet-stream", HttpUtil.contentTypeFor("mystery.bin"))
    }

    @Test
    fun `response headers are well formed and never allow cross-origin reads`() {
        val header = HttpUtil.headerBlock(200, "application/json; charset=utf-8", 42)
        assertTrue(header.startsWith("HTTP/1.1 200 OK\r\n"))
        assertTrue(header.contains("Content-Length: 42\r\n"))
        assertTrue(header.contains("Cache-Control: no-store\r\n"))
        assertTrue(header.endsWith("\r\n\r\n"))
        assertFalse(header.contains("Access-Control-Allow-Origin"))
    }

    @Test
    fun `status line text is set for every status the server emits`() {
        assertEquals("Unauthorized", HttpUtil.statusText(401))
        assertEquals("Not Found", HttpUtil.statusText(404))
        assertEquals("Too Many Requests", HttpUtil.statusText(429))
    }
}
