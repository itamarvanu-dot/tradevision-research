package com.itamar.smsbridge

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * A second, independent way back up.
 *
 * The service already asks to be restarted (START_STICKY) and re-opens its own socket, but
 * both of those die with the process. An alarm lives in the system instead, so it survives
 * the process being killed outright — which is exactly what Samsung's battery manager does.
 *
 * Starting a foreground service from an alarm is blocked on Android 12+ unless the app is
 * exempt from battery optimisation, so this is a fallback and not a guarantee. That is why
 * the app pushes the user to grant that exemption.
 */
object Watchdog {

    private const val TAG = "SmsBridgeWatchdog"
    private const val INTERVAL_MS = 15 * 60 * 1000L
    private const val REQUEST_CODE = 42

    fun schedule(context: Context) {
        val alarms = context.getSystemService(AlarmManager::class.java) ?: return
        // A one-shot alarm re-armed on each firing: unlike setRepeating, this still fires
        // while the device is dozing.
        alarms.setAndAllowWhileIdle(
            AlarmManager.RTC_WAKEUP,
            System.currentTimeMillis() + INTERVAL_MS,
            pendingIntent(context),
        )
    }

    fun cancel(context: Context) {
        context.getSystemService(AlarmManager::class.java)?.cancel(pendingIntent(context))
    }

    private fun pendingIntent(context: Context): PendingIntent = PendingIntent.getBroadcast(
        context,
        REQUEST_CODE,
        Intent(context, Receiver::class.java).setAction(ACTION_CHECK),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    const val ACTION_CHECK = "com.itamar.smsbridge.WATCHDOG_CHECK"

    class Receiver : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action != ACTION_CHECK) return
            val prefs = Prefs(context)

            if (!prefs.alwaysOn || prefs.manuallyStopped) {
                Watchdog.cancel(context)
                return
            }
            if (!SmsRepository.hasSmsPermission(context)) {
                Log.i(TAG, "SMS permission missing — not restarting, will check again")
                Watchdog.schedule(context)
                return
            }

            // Starting a service that is already running is a no-op beyond a settings refresh.
            if (!BridgeService.State.running) {
                Log.w(TAG, "bridge was down — bringing it back")
            }
            BridgeService.start(context)
            Watchdog.schedule(context)
        }
    }
}
