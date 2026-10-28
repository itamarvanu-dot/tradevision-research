package com.itamar.smsbridge

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import com.google.firebase.FirebaseApp
import com.google.firebase.FirebaseOptions

class App : Application() {

    override fun onCreate() {
        super.onCreate()
        initFirebase(this)
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_PULLS, getString(R.string.channel_pulls), NotificationManager.IMPORTANCE_LOW)
                .apply { setShowBadge(false) }
        )
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_SHARING, getString(R.string.channel_sharing), NotificationManager.IMPORTANCE_LOW)
                .apply { setShowBadge(false) }
        )
    }

    companion object {
        const val CHANNEL_PULLS = "pulls"
        const val CHANNEL_SHARING = "sharing"

        /**
         * Firebase is configured from the enrollment, not from a google-services.json compiled
         * into the APK, so the same build works for any controller's project. Runs on every
         * process start, including the cold start a push triggers.
         *
         * @return false when the stored config differs from the one already running, which only
         *         a process restart can apply.
         */
        fun initFirebase(context: Context): Boolean {
            val config = Prefs(context).config ?: return true
            val existing = FirebaseApp.getApps(context).firstOrNull { it.name == FirebaseApp.DEFAULT_APP_NAME }
            if (existing != null) {
                val o = existing.options
                return o.applicationId == config.appId && o.projectId == config.projectId
            }
            val options = FirebaseOptions.Builder()
                .setApplicationId(config.appId)
                .setApiKey(config.apiKey)
                .setProjectId(config.projectId)
                .setGcmSenderId(config.senderId)
                .setDatabaseUrl(config.databaseUrl)
                .build()
            FirebaseApp.initializeApp(context, options)
            return true
        }
    }
}
