package com.itamar.smsbridge

import org.json.JSONObject

/** The client-side values Firebase needs to register this phone for pushes. */
data class FirebaseConfig(
    val projectId: String,
    val appId: String,
    val apiKey: String,
    val senderId: String,
    val databaseUrl: String?,
) {
    companion object {
        fun isGoogleServices(json: JSONObject) = json.has("project_info") && json.has("client")

        /** Reads a google-services.json, picking the entry for this app's package. */
        fun fromGoogleServices(json: JSONObject, packageName: String): FirebaseConfig {
            val info = json.getJSONObject("project_info")
            val clients = json.getJSONArray("client")
            var match: JSONObject? = null
            for (i in 0 until clients.length()) {
                val c = clients.getJSONObject(i)
                val pkg = c.optJSONObject("client_info")
                    ?.optJSONObject("android_client_info")
                    ?.optString("package_name")
                if (pkg == packageName) { match = c; break }
            }
            val client = match ?: throw IllegalArgumentException(
                "בקובץ google-services.json אין אפליקציה עם החבילה $packageName"
            )
            return FirebaseConfig(
                projectId = info.getString("project_id"),
                appId = client.getJSONObject("client_info").getString("mobilesdk_app_id"),
                apiKey = client.getJSONArray("api_key").getJSONObject(0).getString("current_key"),
                senderId = info.getString("project_number"),
                databaseUrl = info.optString("firebase_url").ifBlank { null },
            )
        }
    }
}
