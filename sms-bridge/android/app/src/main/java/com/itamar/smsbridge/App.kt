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
        createChannel()
    }

    private fun createChannel() {
        val channel = NotificationChannel(
            CHANNEL_PULLS,
            getString(R.string.channel_pulls),
            NotificationManager.IMPORTANCE_LOW,
        ).apply { setShowBadge(false) }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    companion object {
        const val CHANNEL_PULLS = "pulls"

        /**
         * Firebase is configured from what the user imported, not from a google-services.json
         * compiled into the APK. Runs on every process start, including the cold start Google
         * Play services triggers to deliver a push.
         *
         * @return false when the stored config differs from the one already running, which
         *         only a process restart can apply.
         */
        fun initFirebase(context: Context): Boolean {
            val config = Prefs(context).firebase ?: return true
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
                .apply { config.databaseUrl?.let { setDatabaseUrl(it) } }
                .build()
            FirebaseApp.initializeApp(context, options)
            return true
        }
    }
}
