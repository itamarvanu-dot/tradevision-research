package com.itamar.smsbridge

import android.content.Context
import java.security.SecureRandom

/** Small wrapper over SharedPreferences. The access token lives here and nowhere else. */
class Prefs(context: Context) {

    private val sp = context.applicationContext
        .getSharedPreferences("sms_bridge", Context.MODE_PRIVATE)

    var port: Int
        get() = sp.getInt(KEY_PORT, DEFAULT_PORT)
        set(value) = sp.edit().putInt(KEY_PORT, value).apply()

    /**
     * When set, the bridge stays up indefinitely and comes back by itself after a reboot,
     * so the phone can be left alone. When cleared, the bridge is a temporary thing that
     * shuts down after [autoStopMinutes] and has to be switched on by hand.
     */
    var alwaysOn: Boolean
        get() = sp.getBoolean(KEY_ALWAYS_ON, true)
        set(value) = sp.edit().putBoolean(KEY_ALWAYS_ON, value).apply()

    /**
     * Set when the bridge was switched off deliberately, from the app or the notification.
     * The boot receiver and the alarm watchdog honour it, so "off" means off until the next
     * time the bridge is started by hand.
     */
    var manuallyStopped: Boolean
        get() = sp.getBoolean(KEY_MANUALLY_STOPPED, false)
        set(value) = sp.edit().putBoolean(KEY_MANUALLY_STOPPED, value).apply()

    /** Minutes of inactivity after which the bridge shuts itself down. Ignored when [alwaysOn]. */
    var autoStopMinutes: Int
        get() = sp.getInt(KEY_AUTO_STOP, DEFAULT_AUTO_STOP_MINUTES)
        set(value) = sp.edit().putInt(KEY_AUTO_STOP, value).apply()

    /** Generated lazily on first use so a fresh install always has a token. */
    val token: String
        get() = sp.getString(KEY_TOKEN, null) ?: regenerateToken()

    fun regenerateToken(): String {
        val token = randomToken()
        sp.edit().putString(KEY_TOKEN, token).apply()
        return token
    }

    private fun randomToken(): String {
        val random = SecureRandom()
        val sb = StringBuilder(TOKEN_LENGTH)
        repeat(TOKEN_LENGTH) {
            sb.append(TOKEN_ALPHABET[random.nextInt(TOKEN_ALPHABET.length)])
        }
        return sb.toString()
    }

    companion object {
        const val DEFAULT_PORT = 8080
        const val DEFAULT_AUTO_STOP_MINUTES = 30

        private const val KEY_PORT = "port"
        private const val KEY_ALWAYS_ON = "always_on"
        private const val KEY_MANUALLY_STOPPED = "manually_stopped"
        private const val KEY_AUTO_STOP = "auto_stop_minutes"
        private const val KEY_TOKEN = "token"

        private const val TOKEN_LENGTH = 12

        /** No 0/O/1/I/l — the token gets typed by hand often enough to matter. */
        private const val TOKEN_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
    }
}
