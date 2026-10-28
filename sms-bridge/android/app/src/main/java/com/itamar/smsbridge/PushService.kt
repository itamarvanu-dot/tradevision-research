package com.itamar.smsbridge

import android.app.NotificationManager
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.util.Log
import androidx.core.app.NotificationCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import org.json.JSONObject

/**
 * The only code that runs without the app being open, and only when the controller asks.
 *
 * The controller sends a high-priority FCM data message. Google Play services wakes this
 * process even in Doze and grants a few seconds of network; we read the recent inbox,
 * encrypt it and upload it to this phone's box. Then the process goes back to nothing.
 */
class PushService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        Prefs(this).fcmToken = token
        // The controller addresses this phone by token, so a rotated token must be republished.
        try {
            Enroller.publish(this)
        } catch (e: Exception) {
            Log.w(TAG, "republishing the new token failed; will retry on next app open", e)
        }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val request = PullPayload.parse(message.data) ?: return
        val prefs = Prefs(this)
        val db = prefs.config?.databaseUrl ?: return
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

        val payload = PullPayload.build(request, messages, Enroller.deviceName(), batteryPercent(), now, status)
        try {
            val sealed = Crypto.seal(key, payload.toString())
            Net.putJson(
                db,
                "boxes/$box/inbox",
                JSONObject().put("req", request.req).put("at", now).put("iv", sealed.iv).put("ct", sealed.ct).toString(),
            )
            prefs.lastError = null
            if (status == "ok") {
                prefs.lastPullAt = now
                prefs.lastPullCount = messages.size
                notifyPulled(messages.size, request.req.startsWith("selftest-"), prefs.controllerLabel)
            }
        } catch (e: Exception) {
            prefs.lastError = e.message
            Log.w(TAG, "uploading the reply failed", e)
        }
    }

    /**
     * A quiet, self-dismissing note so the owner of this phone always sees when their
     * messages were shared, and with whom. Transparency is deliberate: this app forwards
     * SMS, and the person it runs for should never be in the dark about it.
     */
    private fun notifyPulled(count: Int, selfTest: Boolean, controller: String?) {
        val text = when {
            selfTest -> getString(R.string.notif_selftest)
            controller != null -> getString(R.string.notif_pulled_to, count, controller)
            else -> getString(R.string.notif_pulled, count)
        }
        val n = NotificationCompat.Builder(this, App.CHANNEL_PULLS)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setSilent(true)
            .setAutoCancel(true)
            .setTimeoutAfter(10 * 60_000L)
            .build()
        try {
            getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, n)
        } catch (_: SecurityException) {
            // Notifications not allowed; the pull itself already succeeded.
        }
    }

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
