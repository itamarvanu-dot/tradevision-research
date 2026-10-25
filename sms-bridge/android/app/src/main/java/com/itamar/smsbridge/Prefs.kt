package com.itamar.smsbridge

import android.content.Context
import org.json.JSONObject

/** Small wrapper over SharedPreferences. Every secret the app holds lives here and nowhere else. */
class Prefs(context: Context) {

    private val sp = context.applicationContext
        .getSharedPreferences("sms_bridge", Context.MODE_PRIVATE)

    var serviceAccount: ServiceAccount?
        get() = sp.getString(KEY_SA, null)?.let { ServiceAccount.parse(JSONObject(it)) }
        set(value) = sp.edit().putString(KEY_SA, value?.toJson()?.toString()).apply()

    var firebase: FirebaseConfig?
        get() {
            val raw = sp.getString(KEY_FIREBASE, null) ?: return null
            val j = JSONObject(raw)
            return FirebaseConfig(
                projectId = j.getString("projectId"),
                appId = j.getString("appId"),
                apiKey = j.getString("apiKey"),
                senderId = j.getString("senderId"),
                databaseUrl = j.optString("databaseUrl").ifBlank { null },
            )
        }
        set(value) {
            val raw = value?.let {
                JSONObject()
                    .put("projectId", it.projectId)
                    .put("appId", it.appId)
                    .put("apiKey", it.apiKey)
                    .put("senderId", it.senderId)
                    .put("databaseUrl", it.databaseUrl ?: "")
                    .toString()
            }
            sp.edit().putString(KEY_FIREBASE, raw).apply()
        }

    /** Random path segment under /boxes. Changing it (with [boxKey]) unpairs the iPhone. */
    var boxId: String?
        get() = sp.getString(KEY_BOX, null)
        set(value) = sp.edit().putString(KEY_BOX, value).apply()

    /** AES key shared with the iPhone through the pairing link only. */
    var boxKey: String?
        get() = sp.getString(KEY_BOX_KEY, null)
        set(value) = sp.edit().putString(KEY_BOX_KEY, value).apply()

    var fcmToken: String?
        get() = sp.getString(KEY_FCM, null)
        set(value) = sp.edit().putString(KEY_FCM, value).apply()

    /** The FCM token most recently written to the setup record the iPhone reads. */
    var publishedToken: String?
        get() = sp.getString(KEY_PUBLISHED, null)
        set(value) = sp.edit().putString(KEY_PUBLISHED, value).apply()

    var pageUrl: String
        get() = sp.getString(KEY_PAGE_URL, null) ?: BuildConfig.DEFAULT_PAGE_URL
        set(value) = sp.edit().putString(KEY_PAGE_URL, value).apply()

    /** Hash of the iPhone page last deployed to Firebase Hosting; a new APK may carry a newer one. */
    var deployedPageHash: String?
        get() = sp.getString(KEY_PAGE_HASH, null)
        set(value) = sp.edit().putString(KEY_PAGE_HASH, value).apply()

    /** Set when the page could not be put on Firebase Hosting; the QR then uses [pageUrl] as is. */
    var hostingError: String?
        get() = sp.getString(KEY_HOSTING_ERROR, null)
        set(value) = sp.edit().putString(KEY_HOSTING_ERROR, value).apply()

    /** Master switch. When off, pull requests from the iPhone are answered with "paused". */
    var enabled: Boolean
        get() = sp.getBoolean(KEY_ENABLED, true)
        set(value) = sp.edit().putBoolean(KEY_ENABLED, value).apply()

    var lastPullAt: Long
        get() = sp.getLong(KEY_LAST_PULL_AT, 0L)
        set(value) = sp.edit().putLong(KEY_LAST_PULL_AT, value).apply()

    var lastPullCount: Int
        get() = sp.getInt(KEY_LAST_PULL_COUNT, 0)
        set(value) = sp.edit().putInt(KEY_LAST_PULL_COUNT, value).apply()

    var lastError: String?
        get() = sp.getString(KEY_LAST_ERROR, null)
        set(value) = sp.edit().putString(KEY_LAST_ERROR, value).apply()

    val isPaired: Boolean
        get() = serviceAccount != null && firebase?.databaseUrl != null &&
            boxId != null && boxKey != null && publishedToken != null

    /** The link inside the QR code. Everything after '#' stays on the iPhone; browsers never send it. */
    fun pairingUrl(): String? {
        val db = firebase?.databaseUrl ?: return null
        val box = boxId ?: return null
        val key = boxKey ?: return null
        val payload = JSONObject().put("d", db).put("b", box).put("k", key).toString()
        return pageUrl + "#p=" + Crypto.b64url(payload.toByteArray(Charsets.UTF_8))
    }

    val tokenCache = object : Google.TokenCache {
        override fun load(): Pair<String, Long>? {
            val t = sp.getString(KEY_ACCESS, null) ?: return null
            return t to sp.getLong(KEY_ACCESS_EXP, 0L)
        }

        override fun store(token: String, expiresAtMs: Long) {
            sp.edit().putString(KEY_ACCESS, token).putLong(KEY_ACCESS_EXP, expiresAtMs).apply()
        }
    }

    fun google(): Google? = serviceAccount?.let { Google(it, tokenCache) }

    fun clearAccessToken() = sp.edit().remove(KEY_ACCESS).remove(KEY_ACCESS_EXP).apply()

    companion object {
        private const val KEY_SA = "service_account"
        private const val KEY_FIREBASE = "firebase"
        private const val KEY_BOX = "box_id"
        private const val KEY_BOX_KEY = "box_key"
        private const val KEY_FCM = "fcm_token"
        private const val KEY_PUBLISHED = "published_token"
        private const val KEY_PAGE_URL = "page_url"
        private const val KEY_PAGE_HASH = "page_hash"
        private const val KEY_HOSTING_ERROR = "hosting_error"
        private const val KEY_ENABLED = "enabled"
        private const val KEY_LAST_PULL_AT = "last_pull_at"
        private const val KEY_LAST_PULL_COUNT = "last_pull_count"
        private const val KEY_LAST_ERROR = "last_error"
        private const val KEY_ACCESS = "access_token"
        private const val KEY_ACCESS_EXP = "access_token_exp"
    }
}
