package com.itamar.smsbridge

import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/**
 * The only networking the sender does: unauthenticated writes to its own box in the
 * Realtime Database. It holds no account and no admin key — the database rules allow a
 * write only to a box the controller (the iPhone) has already provisioned, and the box
 * path is a 128-bit secret that travelled in the enrollment link.
 */
object Net {

    class HttpError(val code: Int, val body: String) : IOException("HTTP $code: ${body.take(300)}")

    fun putJson(dbUrl: String, path: String, json: String) {
        val url = dbUrl.trimEnd('/') + "/" + path.trim('/') + ".json"
        val conn = URL(url).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = "PUT"
            conn.connectTimeout = 10_000
            conn.readTimeout = 15_000
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            conn.outputStream.use { it.write(json.toByteArray(Charsets.UTF_8)) }
            val code = conn.responseCode
            if (code !in 200..299) {
                val err = conn.errorStream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
                throw HttpError(code, err)
            }
        } finally {
            conn.disconnect()
        }
    }
}
