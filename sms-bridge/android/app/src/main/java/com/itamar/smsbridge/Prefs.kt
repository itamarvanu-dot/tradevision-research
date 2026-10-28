package com.itamar.smsbridge

import android.content.Context
import org.json.JSONObject

/** Small wrapper over SharedPreferences. The sender holds only its own box's values here. */
class Prefs(context: Context) {

    private val sp = context.applicationContext
        .getSharedPreferences("sms_bridge", Context.MODE_PRIVATE)

    var config: PublicConfig?
        get() {
            val raw = sp.getString(KEY_CONFIG, null) ?: return null
            val j = JSONObject(raw)
            return PublicConfig(
                projectId = j.getString("projectId"),
                appId = j.getString("appId"),
                apiKey = j.getString("apiKey"),
                senderId = j.getString("senderId"),
                databaseUrl = j.getString("databaseUrl"),
            )
        }
        set(value) {
            val raw = value?.let {
                JSONObject()
                    .put("projectId", it.projectId)
                    .put("appId", it.appId)
                    .put("apiKey", it.apiKey)
                    .put("senderId", it.senderId)
                    .put("databaseUrl", it.databaseUrl)
                    .toString()
            }
            sp.edit().putString(KEY_CONFIG, raw).apply()
        }

    var boxId: String?
        get() = sp.getString(KEY_BOX, null)
        set(value) = sp.edit().putString(KEY_BOX, value).apply()

    var boxKey: String?
        get() = sp.getString(KEY_BOX_KEY, null)
        set(value) = sp.edit().putString(KEY_BOX_KEY, value).apply()

    /** A friendly name for the device the messages are shared with, shown to this phone's owner. */
    var controllerLabel: String?
        get() = sp.getString(KEY_CONTROLLER, null)
        set(value) = sp.edit().putString(KEY_CONTROLLER, value).apply()

    var fcmToken: String?
        get() = sp.getString(KEY_FCM, null)
        set(value) = sp.edit().putString(KEY_FCM, value).apply()

    var publishedToken: String?
        get() = sp.getString(KEY_PUBLISHED, null)
        set(value) = sp.edit().putString(KEY_PUBLISHED, value).apply()

    /** Master switch. When off, pulls are answered with "paused" and no messages are sent. */
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

    val isEnrolled: Boolean
        get() = config != null && boxId != null && boxKey != null && publishedToken != null

    fun clearEnrollment() {
        sp.edit()
            .remove(KEY_CONFIG).remove(KEY_BOX).remove(KEY_BOX_KEY).remove(KEY_CONTROLLER)
            .remove(KEY_FCM).remove(KEY_PUBLISHED).remove(KEY_LAST_PULL_AT)
            .remove(KEY_LAST_PULL_COUNT).remove(KEY_LAST_ERROR)
            .apply()
    }

    companion object {
        private const val KEY_CONFIG = "config"
        private const val KEY_BOX = "box_id"
        private const val KEY_BOX_KEY = "box_key"
        private const val KEY_CONTROLLER = "controller_label"
        private const val KEY_FCM = "fcm_token"
        private const val KEY_PUBLISHED = "published_token"
        private const val KEY_ENABLED = "enabled"
        private const val KEY_LAST_PULL_AT = "last_pull_at"
        private const val KEY_LAST_PULL_COUNT = "last_pull_count"
        private const val KEY_LAST_ERROR = "last_error"
    }
}
