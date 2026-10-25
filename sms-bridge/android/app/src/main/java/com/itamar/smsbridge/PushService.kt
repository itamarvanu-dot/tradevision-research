package com.itamar.smsbridge

import android.app.NotificationManager
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import org.json.JSONObject

/**
 * The only code that runs without the app being open, and only when the iPhone asks.
 *
 * The iPhone sends a high-priority FCM data message. Google Play services wakes this
 * process even in Doze and grants a few seconds of network; we read the recent inbox,
 * encrypt it, upload it to the database and the process goes back to nothing.
 */
class PushService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        val prefs = Prefs(this)
        prefs.fcmToken = token
        // The iPhone addresses this phone by token, so a rotated token must be republished.
        try {
            Pairing.publish(this)
        } catch (e: Exception) {
            Log.w(TAG, "republishing the new token failed; will retry on next app open", e)
        }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val request = PullPayload.parse(message.data) ?: return
        val prefs = Prefs(this)
        val google = prefs.google() ?: return
        val db = prefs.firebase?.databaseUrl ?: return
        val box = prefs.boxId ?: return
        val key = prefs.boxKey ?: return

        val now = System.currentTimeMillis()
        val status = when {
            !prefs.enabled -> "paused"
            !SmsRepository.hasSmsPermission(this) -> "no_permission"
            else -> "ok"
        }
        val messages = if (status == "ok") {
            SmsRepository.query(this, request.limit, PullPayload.since(request, now))
        } else {
            emptyList()
        }

        val payload = PullPayload.build(request, messages, deviceName(), batteryPercent(), now, status)
        try {
            val sealed = Crypto.seal(key, payload.toString())
            google.dbPut(
                db,
                "boxes/$box/inbox",
                JSONObject().put("req", request.req).put("at", now).put("iv", sealed.iv).put("ct", sealed.ct),
            )
            prefs.lastError = null
            if (status == "ok") {
                prefs.lastPullAt = now
                prefs.lastPullCount = messages.size
                notifyPulled(messages.size, request.req.startsWith("selftest-"))
            }
        } catch (e: Exception) {
            prefs.lastError = e.message
            Log.w(TAG, "uploading the reply failed", e)
            if (e is Google.HttpError && e.code == 401) prefs.clearAccessToken()
        }
    }

    /**
     * A quiet, self-dismissing note. It is also how you would notice someone else pulling,
     * and Android treats high-priority pushes that lead to a visible notification as
     * legitimate, which keeps them high-priority over time.
     */
    private fun notifyPulled(count: Int, selfTest: Boolean) {
        val text = if (selfTest) getString(R.string.notif_selftest) else getString(R.string.notif_pulled, count)
        val n = NotificationCompat.Builder(this, App.CHANNEL_PULLS)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setSilent(true)
            .setAutoCancel(true)
            .setTimeoutAfter(5 * 60_000L)
            .build()
        try {
            getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, n)
        } catch (_: SecurityException) {
            // Notifications not allowed; the pull itself already succeeded.
        }
    }

    private fun deviceName() = Build.MANUFACTURER.replaceFirstChar { it.uppercase() } + " " + Build.MODEL

    private fun batteryPercent(): Int? {
        val intent = registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return null
        val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        return if (level >= 0 && scale > 0) level * 100 / scale else null
    }

    companion object {
        private const val TAG = "SmsBridgePush"
        private const val NOTIFICATION_ID = 7
    }
}
