package com.itamar.smsbridge

import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** The handful of Google REST calls the app makes, over plain HttpURLConnection. */
class Google(private val sa: ServiceAccount, private val tokenCache: TokenCache? = null) {

    class HttpError(val code: Int, val body: String) : IOException("HTTP $code: ${body.take(300)}")

    /** Lets an access token survive between pushes, so most pulls skip the OAuth round trip. */
    interface TokenCache {
        fun load(): Pair<String, Long>?
        fun store(token: String, expiresAtMs: Long)
    }

    // ----------------------------------------------------------------- auth

    fun accessToken(): String {
        val now = System.currentTimeMillis()
        tokenCache?.load()?.let { (token, expiresAt) -> if (expiresAt - now > 5 * 60_000) return token }

        val form = "grant_type=" + enc("urn:ietf:params:oauth:grant-type:jwt-bearer") +
            "&assertion=" + enc(sa.assertion(SCOPES, now / 1000))
        val res = JSONObject(request("POST", sa.tokenUri, form, null, "application/x-www-form-urlencoded"))
        val token = res.getString("access_token")
        tokenCache?.store(token, now + res.optLong("expires_in", 3600) * 1000)
        return token
    }

    // ------------------------------------------------------------- database

    fun dbPut(dbUrl: String, path: String, value: Any) {
        request("PUT", dbPath(dbUrl, path), value.toString(), accessToken())
    }

    fun dbDelete(dbUrl: String, path: String) {
        request("DELETE", dbPath(dbUrl, path), null, accessToken())
    }

    /** Replaces the project's database rules. The project is dedicated to this app. */
    fun setRules(dbUrl: String, rules: JSONObject) {
        request("PUT", dbUrl.trimEnd('/') + "/.settings/rules.json", rules.toString(2), accessToken())
    }

    /** The project's default Realtime Database URL, creating the database if there is none. */
    fun ensureDatabase(): String {
        val base = "https://firebasedatabase.googleapis.com/v1beta/projects/${sa.projectId}/locations"
        val list = JSONObject(request("GET", "$base/-/instances", null, accessToken()))
        val instances = list.optJSONArray("instances") ?: JSONArray()
        for (i in 0 until instances.length()) {
            val url = instances.getJSONObject(i).optString("databaseUrl")
            if (url.isNotBlank()) return url
        }
        val created = JSONObject(
            request(
                "POST",
                "$base/$DEFAULT_DB_LOCATION/instances?databaseId=" + enc("${sa.projectId}-default-rtdb"),
                JSONObject().put("type", "DEFAULT_DATABASE").toString(),
                accessToken(),
            )
        )
        return created.getString("databaseUrl")
    }

    // ------------------------------------------------- firebase app registry

    /**
     * Finds (or registers) this Android app in the Firebase project and returns its client
     * config — so the only file the user really has to bring is the service-account key.
     */
    fun androidAppConfig(packageName: String): FirebaseConfig {
        val base = "https://firebase.googleapis.com/v1beta1/projects/${sa.projectId}"
        var appId: String? = null

        val apps = JSONObject(request("GET", "$base/androidApps?pageSize=100", null, accessToken()))
            .optJSONArray("apps") ?: JSONArray()
        for (i in 0 until apps.length()) {
            val app = apps.getJSONObject(i)
            if (app.optString("packageName") == packageName) { appId = app.getString("appId"); break }
        }

        if (appId == null) {
            var op = JSONObject(
                request(
                    "POST",
                    "$base/androidApps",
                    JSONObject().put("packageName", packageName).put("displayName", "SMS Bridge").toString(),
                    accessToken(),
                )
            )
            val deadline = System.currentTimeMillis() + 60_000
            while (!op.optBoolean("done") && System.currentTimeMillis() < deadline) {
                Thread.sleep(1500)
                op = JSONObject(request("GET", "https://firebase.googleapis.com/v1beta1/" + op.getString("name"), null, accessToken()))
            }
            op.optJSONObject("error")?.let { throw IOException(it.optString("message")) }
            appId = op.optJSONObject("response")?.optString("appId")
                ?: throw IOException("רישום האפליקציה בפיירבייס לא הסתיים בזמן")
        }

        val config = JSONObject(request("GET", "$base/androidApps/$appId/config", null, accessToken()))
        val file = String(java.util.Base64.getDecoder().decode(config.getString("configFileContents")))
        return FirebaseConfig.fromGoogleServices(JSONObject(file), packageName)
    }

    // ------------------------------------------------------------- messaging

    fun sendPush(fcmToken: String, data: Map<String, String>) {
        val body = JSONObject().put(
            "message",
            JSONObject()
                .put("token", fcmToken)
                .put("data", JSONObject(data))
                .put("android", JSONObject().put("priority", "HIGH").put("ttl", "120s")),
        )
        request(
            "POST",
            "https://fcm.googleapis.com/v1/projects/${sa.projectId}/messages:send",
            body.toString(),
            accessToken(),
        )
    }

    // ------------------------------------------------------------------ http

    private fun dbPath(dbUrl: String, path: String) = dbUrl.trimEnd('/') + "/" + path.trim('/') + ".json"

    private fun request(
        method: String,
        url: String,
        body: String?,
        bearer: String?,
        contentType: String = "application/json",
    ): String {
        val conn = URL(url).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = method
            conn.connectTimeout = 10_000
            conn.readTimeout = 15_000
            if (bearer != null) conn.setRequestProperty("Authorization", "Bearer $bearer")
            if (body != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "$contentType; charset=utf-8")
                conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
            if (code !in 200..299) throw HttpError(code, text)
            return text
        } finally {
            conn.disconnect()
        }
    }

    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

    companion object {
        const val SCOPES = "https://www.googleapis.com/auth/cloud-platform " +
            "https://www.googleapis.com/auth/firebase.database " +
            "https://www.googleapis.com/auth/firebase.messaging " +
            "https://www.googleapis.com/auth/userinfo.email"

        private const val DEFAULT_DB_LOCATION = "us-central1"

        /**
         * Locked down: only the service account (which bypasses rules) can read or write,
         * except each box's encrypted setup record, which the iPhone fetches once with the
         * key from its pairing link.
         */
        val RULES: JSONObject = JSONObject(
            """
            {"rules": {
              ".read": false, ".write": false,
              "boxes": { "${'$'}box": { "setup": { ".read": true } } }
            }}
            """.trimIndent()
        )
    }
}
