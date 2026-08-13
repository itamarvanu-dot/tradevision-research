package com.itamar.smsbridge

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * Brings the bridge back after a reboot or an app update, so the phone can be left alone.
 * Does nothing unless [Prefs.alwaysOn] is set.
 */
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action ?: return
        if (action !in HANDLED_ACTIONS) return
        if (!Prefs(context).alwaysOn) return

        // Without the SMS permission the bridge has nothing to serve, and asking for it needs
        // an activity — so wait for the user to open the app rather than starting a useless service.
        if (!SmsRepository.hasSmsPermission(context)) {
            Log.i(TAG, "not restarting after $action: SMS permission is not granted")
            return
        }

        Log.i(TAG, "restarting the bridge after $action")
        BridgeService.start(context)
    }

    companion object {
        private const val TAG = "SmsBridgeBoot"

        private val HANDLED_ACTIONS = setOf(
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_MY_PACKAGE_REPLACED,
            // Samsung and a few other OEMs send this instead on a "fast" boot.
            "android.intent.action.QUICKBOOT_POWERON",
            "com.htc.intent.action.QUICKBOOT_POWERON",
        )
    }
}
