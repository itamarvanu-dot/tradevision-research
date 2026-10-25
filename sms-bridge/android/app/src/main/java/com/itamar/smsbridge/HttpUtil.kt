package com.itamar.smsbridge

import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.URLDecoder

/**
 * The protocol plumbing behind [HttpServer], kept free of Android types so it can be
 * covered by plain JVM unit tests.
 */
internal object HttpUtil {

    const val MAX_HEADER_BYTES = 8192


    /**
     * Writes responses for one request.
     *
     * Body inclusion is decided here, once, from the request method — a HEAD response carries
     * the same Content-Length as a GET but no body. Leaving that to each call site is how you
     * end up announcing a body you never send, which makes the client wait for bytes that
     * never arrive.
     */
    class Responder(private val out: OutputStream, method: String) {

        private val includeBody = !method.equals("HEAD", ignoreCase = true)

        fun send(status: Int, contentType: String, body: ByteArray) {
            out.write(headerBlock(status, contentType, body.size).toByteArray(Charsets.US_ASCII))
            if (includeBody) out.write(body)
        }

        fun sendText(status: Int, text: String) =
            send(status, "text/plain; charset=utf-8", text.toByteArray(Charsets.UTF_8))

        fun sendJson(status: Int, json: String) =
            send(status, "application/json; charset=utf-8", json.toByteArray(Charsets.UTF_8))
    }

    /** A parsed request line plus the headers we care about. */
    data class Request(
        val method: String,
        val path: String,
        val query: Map<String, String>,
        val headers: Map<String, String>,
    )

    /**
     * Reads one request off [input]. Returns null when the peer sent nothing, and throws
     * [IOException] on a header line long enough to look like an attack rather than a browser.
     */
    fun readRequest(input: InputStream): Request? {
        val requestLine = readLine(input) ?: return null
        val parts = requestLine.split(' ')
        if (parts.size < 2) return null

        val headers = HashMap<String, String>()
        while (true) {
            val line = readLine(input) ?: break
            if (line.isEmpty()) break
            val colon = line.indexOf(':')
            if (colon > 0) {
                headers[line.substring(0, colon).trim().lowercase()] = line.substring(colon + 1).trim()
            }
        }

        val target = parts[1]
        val queryStart = target.indexOf('?')
        return Request(
            method = parts[0].uppercase(),
            path = if (queryStart >= 0) target.substring(0, queryStart) else target,
            query = if (queryStart >= 0) parseQuery(target.substring(queryStart + 1)) else emptyMap(),
            headers = headers,
        )
    }

    fun readLine(input: InputStream): String? {
        val buffer = ByteArrayOutputStream(128)
        while (true) {
            val b = input.read()
            if (b == -1) return if (buffer.size() == 0) null else buffer.toString("UTF-8")
            if (b == '\n'.code) break
            if (b != '\r'.code) buffer.write(b)
            if (buffer.size() > MAX_HEADER_BYTES) throw IOException("header line too long")
        }
        return buffer.toString("UTF-8")
    }

    fun parseQuery(raw: String): Map<String, String> {
        val out = HashMap<String, String>()
        for (pair in raw.split('&')) {
            if (pair.isEmpty()) continue
            val eq = pair.indexOf('=')
            val key = if (eq >= 0) pair.substring(0, eq) else pair
            val value = if (eq >= 0) pair.substring(eq + 1) else ""
            try {
                out[URLDecoder.decode(key, "UTF-8")] = URLDecoder.decode(value, "UTF-8")
            } catch (_: Exception) {
                // Malformed escape — drop the parameter rather than failing the whole request.
            }
        }
        return out
    }

    /** Compares without leaking the length of the matching prefix through timing. */
    fun constantTimeEquals(a: String, b: String): Boolean {
        if (a.isEmpty() || b.isEmpty()) return false
        if (a.length != b.length) return false
        var diff = 0
        for (i in a.indices) diff = diff or (a[i].code xor b[i].code)
        return diff == 0
    }

    /**
     * Maps a request path to a file name under `assets/web`, or null when the path could
     * escape that directory. Only flat names are ever served.
     */
    fun assetNameFor(path: String): String? {
        val name = if (path == "/" || path.isEmpty()) "index.html" else path.removePrefix("/")
        if (name.isEmpty() || name.contains("..") || name.contains('/') || name.contains('\\')) return null
        if (name.startsWith(".")) return null
        return name
    }

    fun contentTypeFor(name: String): String = when {
        name.endsWith(".html") -> "text/html; charset=utf-8"
        name.endsWith(".webmanifest") -> "application/manifest+json; charset=utf-8"
        name.endsWith(".svg") -> "image/svg+xml"
        name.endsWith(".png") -> "image/png"
        name.endsWith(".css") -> "text/css; charset=utf-8"
        name.endsWith(".js") -> "text/javascript; charset=utf-8"
        else -> "application/octet-stream"
    }

    fun statusText(status: Int): String = when (status) {
        200 -> "OK"
        400 -> "Bad Request"
        401 -> "Unauthorized"
        404 -> "Not Found"
        405 -> "Method Not Allowed"
        429 -> "Too Many Requests"
        else -> "Error"
    }

    /** Response headers. No CORS header is emitted, so only our own page can read the API. */
    fun headerBlock(status: Int, contentType: String, contentLength: Int): String = buildString {
        append("HTTP/1.1 ").append(status).append(' ').append(statusText(status)).append("\r\n")
        append("Content-Type: ").append(contentType).append("\r\n")
        append("Content-Length: ").append(contentLength).append("\r\n")
        append("Cache-Control: no-store\r\n")
        append("X-Content-Type-Options: nosniff\r\n")
        append("Referrer-Policy: no-referrer\r\n")
        append("Connection: close\r\n\r\n")
    }

    /** The token may arrive in a header (preferred) or a query parameter (QR / typed URL). */
    fun tokenFrom(request: Request): String =
        request.headers["x-bridge-token"] ?: request.query["token"] ?: request.query["t"] ?: ""
}
