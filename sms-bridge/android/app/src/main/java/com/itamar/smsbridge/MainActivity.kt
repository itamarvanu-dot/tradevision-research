package com.itamar.smsbridge

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.ImageView
import android.widget.Spinner
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs

    private lateinit var statusHeader: TextView
    private lateinit var statusSub: TextView
    private lateinit var btnToggle: Button
    private lateinit var errorText: TextView
    private lateinit var addressBlock: View
    private lateinit var qrImage: ImageView
    private lateinit var urlText: TextView
    private lateinit var tokenText: TextView
    private lateinit var alwaysOnSwitch: Switch
    private lateinit var reachText: TextView
    private lateinit var reachHint: TextView
    private lateinit var autoStopSpinner: Spinner
    private lateinit var autoStopPending: TextView
    private lateinit var permSms: TextView
    private lateinit var permContacts: TextView

    private val handler = Handler(Looper.getMainLooper())
    private var renderedQrUrl: String? = null
    private val stateListener: () -> Unit = { render() }
    private val ticker = object : Runnable {
        override fun run() {
            render()
            handler.postDelayed(this, TICK_MS)
        }
    }

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { render() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        prefs = Prefs(this)

        statusHeader = findViewById(R.id.statusHeader)
        statusSub = findViewById(R.id.statusSub)
        btnToggle = findViewById(R.id.btnToggle)
        errorText = findViewById(R.id.errorText)
        addressBlock = findViewById(R.id.addressBlock)
        qrImage = findViewById(R.id.qrImage)
        urlText = findViewById(R.id.urlText)
        tokenText = findViewById(R.id.tokenText)
        alwaysOnSwitch = findViewById(R.id.alwaysOnSwitch)
        reachText = findViewById(R.id.reachText)
        reachHint = findViewById(R.id.reachHint)
        autoStopSpinner = findViewById(R.id.autoStopSpinner)
        autoStopPending = findViewById(R.id.autoStopPending)
        permSms = findViewById(R.id.permSms)
        permContacts = findViewById(R.id.permContacts)

        btnToggle.setOnClickListener { toggleBridge() }
        findViewById<Button>(R.id.btnCopy).setOnClickListener { copyUrl() }
        findViewById<Button>(R.id.btnShare).setOnClickListener { shareUrl() }
        findViewById<Button>(R.id.btnNewToken).setOnClickListener { regenerateToken() }
        findViewById<Button>(R.id.btnGrant).setOnClickListener { requestPermissions() }
        findViewById<Button>(R.id.btnBattery).setOnClickListener { openBatterySettings() }

        alwaysOnSwitch.isChecked = prefs.alwaysOn
        alwaysOnSwitch.setOnCheckedChangeListener { _, checked ->
            prefs.alwaysOn = checked
            // Re-issuing the start command applies the new mode to a bridge that is already up.
            if (BridgeService.State.running) BridgeService.start(this)
            render()
        }

        setUpAutoStopSpinner()
    }

    override fun onStart() {
        super.onStart()
        BridgeService.State.addListener(stateListener)
        handler.post(ticker)
        render()
    }

    override fun onStop() {
        BridgeService.State.removeListener(stateListener)
        handler.removeCallbacks(ticker)
        super.onStop()
    }

    // ------------------------------------------------------------- Actions

    private fun toggleBridge() {
        if (BridgeService.State.running) {
            BridgeService.stop(this)
            return
        }
        if (!SmsRepository.hasSmsPermission(this)) {
            requestPermissions()
            return
        }
        BridgeService.State.lastError = null
        BridgeService.start(this)
    }

    private fun requestPermissions() {
        val wanted = mutableListOf(Manifest.permission.READ_SMS, Manifest.permission.READ_CONTACTS)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            wanted.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        permissionLauncher.launch(wanted.toTypedArray())
    }

    private fun copyUrl() {
        val url = pairingUrl() ?: return
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.setPrimaryClip(ClipData.newPlainText("SMS Bridge", url))
        Toast.makeText(this, R.string.copied, Toast.LENGTH_SHORT).show()
    }

    private fun shareUrl() {
        val url = pairingUrl() ?: return
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_TEXT, url)
        }
        startActivity(Intent.createChooser(intent, getString(R.string.btn_share)))
    }

    private fun regenerateToken() {
        prefs.regenerateToken()
        render()
    }

    private fun openBatterySettings() {
        val intent = Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
        try {
            startActivity(intent)
        } catch (_: Exception) {
            startActivity(
                Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                    .setData(Uri.fromParts("package", packageName, null))
            )
        }
    }

    private fun setUpAutoStopSpinner() {
        val labels = AUTO_STOP_OPTIONS.map { getString(it.second) }
        autoStopSpinner.adapter = ArrayAdapter(
            this,
            android.R.layout.simple_spinner_dropdown_item,
            labels,
        )
        val current = AUTO_STOP_OPTIONS.indexOfFirst { it.first == prefs.autoStopMinutes }
        autoStopSpinner.setSelection(if (current >= 0) current else 2)

        autoStopSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                val minutes = AUTO_STOP_OPTIONS[position].first
                if (minutes != prefs.autoStopMinutes) {
                    prefs.autoStopMinutes = minutes
                    // Restarting applies the new timeout to a bridge that is already up.
                    if (BridgeService.State.running) BridgeService.start(this@MainActivity)
                }
            }

            override fun onNothingSelected(parent: AdapterView<*>?) = Unit
        }
    }

    // ------------------------------------------------------------ Rendering

    /**
     * The URL the iPhone opens: host, port and token in one scannable string. Prefers the
     * Tailscale address when there is one, since that keeps working away from home.
     */
    private fun pairingUrl(): String? {
        val address = Net.preferred() ?: return null
        return "http://${address.ip}:${prefs.port}/?t=${prefs.token}"
    }

    private fun render() {
        val running = BridgeService.State.running

        statusHeader.setText(if (running) R.string.header_on else R.string.header_off)
        statusHeader.setTextColor(if (running) COLOR_ON else COLOR_OFF)
        btnToggle.setText(if (running) R.string.btn_turn_off else R.string.btn_turn_on)

        val url = pairingUrl()
        statusSub.text = when {
            !running -> getString(R.string.subtitle_off)
            url == null -> getString(R.string.no_network)
            else -> getString(R.string.hint_address)
        }

        val error = BridgeService.State.lastError
        errorText.visibility = if (error == null) View.GONE else View.VISIBLE
        errorText.text = error
        errorText.setTextColor(COLOR_OFF)

        // The address is only meaningful while the server is actually listening.
        if (running && url != null) {
            addressBlock.visibility = View.VISIBLE
            urlText.text = url
            // The ticker calls render() every few seconds; only redraw the QR when it changed.
            if (url != renderedQrUrl) {
                qrImage.setImageBitmap(Qr.bitmap(url, QR_SIZE_PX))
                renderedQrUrl = url
            }
        } else {
            addressBlock.visibility = View.GONE
            qrImage.setImageBitmap(null)
            renderedQrUrl = null
        }

        renderReachability()

        tokenText.text = prefs.token

        // The idle timeout is meaningless while the bridge is meant to stay up.
        autoStopSpinner.isEnabled = !prefs.alwaysOn

        val autoStopAt = BridgeService.State.autoStopAt
        if (running && autoStopAt > 0L) {
            val minutesLeft = ((autoStopAt - System.currentTimeMillis()) / 60_000L).toInt().coerceAtLeast(0)
            autoStopPending.visibility = View.VISIBLE
            autoStopPending.text = getString(R.string.auto_stop_pending, minutesLeft + 1)
        } else {
            autoStopPending.visibility = View.GONE
        }

        val hasSms = SmsRepository.hasSmsPermission(this)
        permSms.setText(if (hasSms) R.string.perm_sms_ok else R.string.perm_sms_missing)
        permSms.setTextColor(if (hasSms) COLOR_ON else COLOR_OFF)

        val hasContacts = checkSelfPermission(Manifest.permission.READ_CONTACTS) ==
            android.content.pm.PackageManager.PERMISSION_GRANTED
        permContacts.setText(if (hasContacts) R.string.perm_contacts_ok else R.string.perm_contacts_missing)
    }

    /** Spells out whether the iPhone will be able to reach this phone from outside the house. */
    private fun renderReachability() {
        val address = Net.preferred()
        when (address?.kind) {
            Net.Kind.TAILSCALE -> {
                reachText.text = getString(R.string.reach_tailscale, address.ip)
                reachText.setTextColor(COLOR_ON)
                reachHint.setText(R.string.reach_hint_tailscale)
            }
            Net.Kind.LAN -> {
                reachText.text = getString(R.string.reach_lan, address.ip)
                reachText.setTextColor(COLOR_WARN)
                reachHint.setText(R.string.reach_hint_lan)
            }
            else -> {
                reachText.setText(R.string.reach_none)
                reachText.setTextColor(COLOR_OFF)
                reachHint.setText(R.string.reach_hint_none)
            }
        }
    }

    companion object {
        private const val QR_SIZE_PX = 600
        private const val TICK_MS = 20_000L

        private val COLOR_ON = Color.parseColor("#1B873F")
        private val COLOR_WARN = Color.parseColor("#B26A00")
        private val COLOR_OFF = Color.parseColor("#C62828")

        /** minutes to string resource; 0 means "never auto-stop". */
        private val AUTO_STOP_OPTIONS = listOf(
            5 to R.string.auto_stop_5,
            15 to R.string.auto_stop_15,
            30 to R.string.auto_stop_30,
            60 to R.string.auto_stop_60,
            0 to R.string.auto_stop_never,
        )
    }
}
