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
import android.util.Log
import androidx.core.app.NotificationCompat

/**
 * Keeps [HttpServer] alive.
 *
 * Two modes, chosen by [Prefs.alwaysOn]:
 *  - always on — the phone is left alone. The service is sticky, comes back after a reboot
 *    via [BootReceiver], holds a wake lock, and a watchdog re-opens the socket if it dies.
 *  - temporary — the bridge is switched on by hand and shuts itself down after
 *    [Prefs.autoStopMinutes] without traffic.
 */
class BridgeService : Service() {

    private val handler = Handler(Looper.getMainLooper())
    private var server: HttpServer? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var wakeLock: PowerManager.WakeLock? = null

    private val autoStopRunnable = Runnable { stopSelf() }

    /**
     * OEM battery managers and transient network errors can take the listening socket down
     * without taking the service with it. Nothing would notice until the iPhone failed to
     * connect, so re-open it here instead.
     */
    private val watchdogRunnable = object : Runnable {
        override fun run() {
            val current = server
            if (current != null && !current.isListening()) {
                Log.w(TAG, "listening socket died — restarting it")
                current.stop()
                server = null
                // A failed rebind leaves State.running false and the error visible; the next
                // tick tries again rather than tearing the service down.
                if (startServer(Prefs(this@BridgeService))) {
                    State.lastError = null
                    State.running = true
                    State.notifyChanged()
                }
            }
            refreshNotification()
            handler.postDelayed(this, WATCHDOG_INTERVAL_MS)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val prefs = Prefs(this)

        if (intent?.action == ACTION_STOP) {
            // An explicit stop has to stick: without this the alarm watchdog or the next
            // reboot would helpfully switch the bridge straight back on.
            prefs.manuallyStopped = true
            Watchdog.cancel(this)
            stopSelf()
            return START_NOT_STICKY
        }
        prefs.manuallyStopped = false
        if (server == null) {
            startBridge(prefs)
        } else {
            // Already up: a restart request, e.g. after a settings change.
            scheduleAutoStop(prefs)
        }

        // Sticky only in always-on mode, so the system brings the bridge back if it kills us.
        return if (prefs.alwaysOn) START_STICKY else START_NOT_STICKY
    }

    private fun startBridge(prefs: Prefs) {
        createChannel()
        startForeground(NOTIFICATION_ID, buildNotification(prefs.port))

        if (!startServer(prefs)) {
            stopSelf()
            return
        }

        acquireLocks(prefs)
        scheduleAutoStop(prefs)
        if (prefs.alwaysOn) Watchdog.schedule(this) else Watchdog.cancel(this)
        handler.removeCallbacks(watchdogRunnable)
        handler.postDelayed(watchdogRunnable, WATCHDOG_INTERVAL_MS)

        State.lastError = null
        State.running = true
        State.port = prefs.port
        State.notifyChanged()
    }

    /** Returns false when the port could not be opened. */
    private fun startServer(prefs: Prefs): Boolean {
        val httpServer = HttpServer(
            context = this,
            port = prefs.port,
            tokenProvider = { prefs.token },
            onApiRequest = { handler.post { scheduleAutoStop(prefs) } },
        )
        return try {
            httpServer.start()
            server = httpServer
            true
        } catch (e: Exception) {
            Log.w(TAG, "could not bind port ${prefs.port}", e)
            State.lastError = getString(R.string.error_port_busy, prefs.port)
            State.running = false
            State.notifyChanged()
            false
        }
    }

    private fun scheduleAutoStop(prefs: Prefs) {
        handler.removeCallbacks(autoStopRunnable)
        val minutes = prefs.autoStopMinutes
        if (prefs.alwaysOn || minutes <= 0) {
            State.autoStopAt = 0L
        } else {
            val delay = minutes * 60_000L
            State.autoStopAt = System.currentTimeMillis() + delay
            handler.postDelayed(autoStopRunnable, delay)
        }
        State.notifyChanged()
    }

    @Suppress("DEPRECATION")
    private fun acquireLocks(prefs: Prefs) {
        // Before Android 10 the Wi-Fi radio is parked while the screen is off and the request
        // never arrives. From Android 10 the platform handles this and the constant is
        // deprecated, so only take the lock where it still does something.
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            val wifiManager = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            wifiLock = wifiManager.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, WIFI_LOCK_TAG)
                .apply { setReferenceCounted(false); acquire() }
        }

        val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = powerManager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, WAKE_LOCK_TAG).apply {
            setReferenceCounted(false)
            // An always-on bridge has to answer at any hour, so the lock is held with no
            // timeout. That costs battery — the phone is expected to be on a charger.
            if (prefs.alwaysOn) acquire() else acquire(TEMPORARY_WAKE_LOCK_MS)
        }
    }

    private fun releaseLocks() {
        wifiLock?.takeIf { it.isHeld }?.release()
        wifiLock = null
        wakeLock?.takeIf { it.isHeld }?.release()
        wakeLock = null
    }

    override fun onDestroy() {
        handler.removeCallbacks(autoStopRunnable)
        handler.removeCallbacks(watchdogRunnable)
        server?.stop()
        server = null
        releaseLocks()
        State.running = false
        State.autoStopAt = 0L
        State.notifyChanged()
        super.onDestroy()
    }

    // -------------------------------------------------------- Notification

    private fun createChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.channel_name),
            NotificationManager.IMPORTANCE_LOW,
        ).apply { setShowBadge(false) }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun refreshNotification() {
        if (!State.running) return
        getSystemService(NotificationManager::class.java)
            .notify(NOTIFICATION_ID, buildNotification(State.port))
    }

    private fun buildNotification(port: Int): Notification {
        val address = Net.preferred()
        val text = when {
            address == null -> getString(R.string.notif_no_network)
            address.kind == Net.Kind.TAILSCALE ->
                getString(R.string.notif_remote_ready, "${address.ip}:$port")
            else -> getString(R.string.notif_local_only, "${address.ip}:$port")
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
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
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

        private const val TAG = "SmsBridgeService"
        private const val CHANNEL_ID = "sms_bridge"
        private const val NOTIFICATION_ID = 1001
        private const val WIFI_LOCK_TAG = "SmsBridge:wifi"
        private const val WAKE_LOCK_TAG = "SmsBridge:cpu"
        private const val TEMPORARY_WAKE_LOCK_MS = 6 * 60 * 60 * 1000L
        private const val WATCHDOG_INTERVAL_MS = 5 * 60 * 1000L

        /**
         * Starting a foreground service from the background is blocked on Android 12+ outside
         * a few exemptions, so this can legitimately fail when called from a boot or alarm
         * broadcast on a phone that has not granted the battery-optimization exemption.
         */
        fun start(context: Context): Boolean = try {
            val intent = Intent(context, BridgeService::class.java)
            context.startForegroundService(intent)
            true
        } catch (e: Exception) {
            Log.w(TAG, "could not start the bridge from the background", e)
            false
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, BridgeService::class.java))
        }
    }
}
