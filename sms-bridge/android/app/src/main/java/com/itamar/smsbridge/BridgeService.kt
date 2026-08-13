package com.itamar.smsbridge

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import androidx.core.app.NotificationCompat

/**
 * Keeps [HttpServer] alive while the bridge is on.
 *
 * The bridge is meant to be temporary, so the service shuts itself down after
 * [Prefs.autoStopMinutes] with no API traffic. Every authenticated request pushes that back.
 */
class BridgeService : Service() {

    private val handler = Handler(Looper.getMainLooper())
    private var server: HttpServer? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var wakeLock: PowerManager.WakeLock? = null

    private val autoStopRunnable = Runnable {
        State.lastError = null
        stopSelf()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopSelf()
                return START_NOT_STICKY
            }
        }
        if (server == null) {
            startBridge()
        } else {
            // Already up: this is a restart request, e.g. after the auto-stop timeout changed.
            scheduleAutoStop()
        }
        return START_NOT_STICKY
    }

    private fun startBridge() {
        val prefs = Prefs(this)
        val port = prefs.port

        createChannel()
        startForeground(NOTIFICATION_ID, buildNotification(port))

        val httpServer = HttpServer(
            context = this,
            port = port,
            tokenProvider = { prefs.token },
            onApiRequest = { handler.post { scheduleAutoStop() } },
        )
        try {
            httpServer.start()
        } catch (e: Exception) {
            State.lastError = getString(R.string.error_port_busy, port)
            State.running = false
            State.notifyChanged()
            stopSelf()
            return
        }

        server = httpServer
        acquireLocks()
        scheduleAutoStop()

        State.lastError = null
        State.running = true
        State.port = port
        State.notifyChanged()
    }

    private fun scheduleAutoStop() {
        handler.removeCallbacks(autoStopRunnable)
        val minutes = Prefs(this).autoStopMinutes
        if (minutes <= 0) {
            State.autoStopAt = 0L
        } else {
            val delay = minutes * 60_000L
            State.autoStopAt = System.currentTimeMillis() + delay
            handler.postDelayed(autoStopRunnable, delay)
        }
        State.notifyChanged()
    }

    @Suppress("DEPRECATION")
    private fun acquireLocks() {
        // Without the Wi-Fi lock, older Android parks the radio while the screen is off and the
        // iPhone's request never arrives. From Android 10 the platform handles this itself, and
        // WIFI_MODE_FULL_HIGH_PERF is deprecated, so only take the lock where it still does work.
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            val wifiManager = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            wifiLock = wifiManager.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, WIFI_LOCK_TAG)
                .apply { setReferenceCounted(false); acquire() }
        }

        val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = powerManager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, WAKE_LOCK_TAG)
            .apply { setReferenceCounted(false); acquire(MAX_WAKE_LOCK_MS) }
    }

    private fun releaseLocks() {
        wifiLock?.takeIf { it.isHeld }?.release()
        wifiLock = null
        wakeLock?.takeIf { it.isHeld }?.release()
        wakeLock = null
    }

    override fun onDestroy() {
        handler.removeCallbacks(autoStopRunnable)
        server?.stop()
        server = null
        releaseLocks()
        State.running = false
        State.autoStopAt = 0L
        State.notifyChanged()
        super.onDestroy()
    }

    private fun createChannel() {
        val manager = getSystemService(NotificationManager::class.java)
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.channel_name),
            NotificationManager.IMPORTANCE_LOW,
        ).apply { setShowBadge(false) }
        manager.createNotificationChannel(channel)
    }

    private fun buildNotification(port: Int): Notification {
        val ip = Net.localIpv4()
        val text = if (ip == null) {
            getString(R.string.notif_no_network)
        } else {
            "http://$ip:$port"
        }

        val openIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val stopIntent = PendingIntent.getService(
            this,
            1,
            Intent(this, BridgeService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE,
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(getString(R.string.notif_title))
            .setContentText(text)
            .setOngoing(true)
            .setSilent(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setContentIntent(openIntent)
            .addAction(0, getString(R.string.notif_stop), stopIntent)
            .build()
    }

    /** Shared, process-local view of whether the bridge is up. Read by [MainActivity]. */
    object State {
        @Volatile var running: Boolean = false
        @Volatile var port: Int = Prefs.DEFAULT_PORT
        @Volatile var autoStopAt: Long = 0L
        @Volatile var lastError: String? = null

        private val listeners = mutableListOf<() -> Unit>()
        private val mainHandler = Handler(Looper.getMainLooper())

        fun addListener(listener: () -> Unit) = synchronized(listeners) { listeners.add(listener) }
        fun removeListener(listener: () -> Unit) = synchronized(listeners) { listeners.remove(listener) }

        fun notifyChanged() {
            val snapshot = synchronized(listeners) { listeners.toList() }
            mainHandler.post { snapshot.forEach { it() } }
        }
    }

    companion object {
        const val ACTION_STOP = "com.itamar.smsbridge.STOP"

        private const val CHANNEL_ID = "sms_bridge"
        private const val NOTIFICATION_ID = 1001
        private const val WIFI_LOCK_TAG = "SmsBridge:wifi"
        private const val WAKE_LOCK_TAG = "SmsBridge:cpu"
        private const val MAX_WAKE_LOCK_MS = 6 * 60 * 60 * 1000L

        fun start(context: Context) {
            val intent = Intent(context, BridgeService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, BridgeService::class.java))
        }
    }
}
