package com.itamar.smsbridge

import android.Manifest
import android.annotation.SuppressLint
import android.app.AlertDialog
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.text.format.DateUtils
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.SwitchCompat
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import kotlin.concurrent.thread
import kotlin.system.exitProcess

class MainActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs

    private lateinit var statusHeader: TextView
    private lateinit var statusSub: TextView
    private lateinit var enabledSwitch: SwitchCompat
    private lateinit var lastPull: TextView
    private lateinit var lastError: TextView
    private lateinit var permSms: TextView
    private lateinit var permContacts: TextView
    private lateinit var btnGrant: Button
    private lateinit var enrollBlock: View
    private lateinit var enrollInput: EditText
    private lateinit var enrollProgress: TextView
    private lateinit var manageBlock: View
    private lateinit var sharingWith: TextView
    private lateinit var hibernation: TextView

    private var busy = false

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { render() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        prefs = Prefs(this)

        statusHeader = findViewById(R.id.statusHeader)
        statusSub = findViewById(R.id.statusSub)
        enabledSwitch = findViewById(R.id.enabledSwitch)
        lastPull = findViewById(R.id.lastPull)
        lastError = findViewById(R.id.lastError)
        permSms = findViewById(R.id.permSms)
        permContacts = findViewById(R.id.permContacts)
        btnGrant = findViewById(R.id.btnGrant)
        enrollBlock = findViewById(R.id.enrollBlock)
        enrollInput = findViewById(R.id.enrollInput)
        enrollProgress = findViewById(R.id.enrollProgress)
        manageBlock = findViewById(R.id.manageBlock)
        sharingWith = findViewById(R.id.sharingWith)
        hibernation = findViewById(R.id.hibernation)

        enabledSwitch.setOnCheckedChangeListener { _, checked ->
            prefs.enabled = checked
            render()
        }
        btnGrant.setOnClickListener { requestPermissions() }
        findViewById<Button>(R.id.btnEnroll).setOnClickListener { enroll(enrollInput.text.toString()) }
        findViewById<Button>(R.id.btnUnenroll).setOnClickListener { confirmUnenroll() }
        findViewById<Button>(R.id.btnAppSettings).setOnClickListener { openAppSettings() }
        findViewById<Button>(R.id.btnBattery).setOnClickListener { requestUnrestrictedBattery() }

        handleEnrollIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleEnrollIntent(intent)
    }

    override fun onResume() {
        super.onResume()
        render()
        if (prefs.isEnrolled) {
            postSharingNotice()
            if (prefs.fcmToken != null && prefs.fcmToken != prefs.publishedToken) {
                background { Enroller.publish(this) }
            }
        }
    }

    // ------------------------------------------------------------- Actions

    private fun handleEnrollIntent(intent: Intent?) {
        val data = intent?.data ?: return
        if (data.scheme == "smsbridge") enroll(data.toString())
    }

    private fun requestPermissions() {
        val wanted = mutableListOf(Manifest.permission.READ_SMS, Manifest.permission.READ_CONTACTS)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            wanted.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        permissionLauncher.launch(wanted.toTypedArray())
    }

    private fun enroll(input: String) {
        if (busy) return
        val enrollment = Enrollment.parse(input)
        if (enrollment == null) {
            showEnrollMessage(getString(R.string.err_bad_link), error = true)
            return
        }
        busy = true
        render()
        showEnrollMessage(getString(R.string.working), error = false)
        thread(name = "enroll") {
            val result = runCatching {
                Enroller.enroll(this, enrollment) { step -> runOnUiThread { showEnrollMessage(getString(step), false) } }
            }
            runOnUiThread {
                busy = false
                result.onSuccess { done ->
                    if (done) {
                        enrollInput.setText("")
                        showEnrollMessage(getString(R.string.enroll_done), error = false)
                    } else {
                        restartForNewProject()
                    }
                }.onFailure { e -> showEnrollMessage(e.message ?: e.toString(), error = true) }
                render()
            }
        }
    }

    private fun restartForNewProject() {
        Toast.makeText(this, R.string.restarting, Toast.LENGTH_LONG).show()
        val intent = packageManager.getLaunchIntentForPackage(packageName)!!
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        startActivity(intent)
        exitProcess(0)
    }

    private fun confirmUnenroll() {
        AlertDialog.Builder(this)
            .setMessage(R.string.unenroll_confirm)
            .setPositiveButton(android.R.string.ok) { _, _ ->
                Enroller.unenroll(this)
                getSystemService(NotificationManager::class.java).cancel(SHARING_NOTICE_ID)
                render()
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun openAppSettings() {
        startActivity(
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                .setData(Uri.fromParts("package", packageName, null))
        )
    }

    @SuppressLint("BatteryLife")
    private fun requestUnrestrictedBattery() {
        try {
            startActivity(
                Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                    .setData(Uri.fromParts("package", packageName, null))
            )
        } catch (_: Exception) {
            openAppSettings()
        }
    }

    private fun background(block: () -> Unit) {
        thread {
            val error = runCatching(block).exceptionOrNull()
            runOnUiThread {
                if (error != null) Toast.makeText(this, error.message, Toast.LENGTH_LONG).show()
                render()
            }
        }
    }

    /** A standing, visible reminder that this phone shares its SMS, and with whom. */
    private fun postSharingNotice() {
        if (!prefs.enabled) {
            getSystemService(NotificationManager::class.java).cancel(SHARING_NOTICE_ID)
            return
        }
        val who = prefs.controllerLabel
        val text = if (who != null) getString(R.string.sharing_notice_with, who) else getString(R.string.sharing_notice)
        val open = android.app.PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            android.app.PendingIntent.FLAG_IMMUTABLE or android.app.PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val n = NotificationCompat.Builder(this, App.CHANNEL_SHARING)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOngoing(true)
            .setSilent(true)
            .setContentIntent(open)
            .build()
        try {
            getSystemService(NotificationManager::class.java).notify(SHARING_NOTICE_ID, n)
        } catch (_: SecurityException) { /* notifications off */ }
    }

    // --------------------------------------------------------------- View

    private fun showEnrollMessage(text: String, error: Boolean) {
        enrollProgress.visibility = View.VISIBLE
        enrollProgress.text = text
        enrollProgress.setTextColor(if (error) 0xFFE53935.toInt() else statusSub.currentTextColor)
    }

    private fun render() {
        val smsOk = SmsRepository.hasSmsPermission(this)
        val contactsOk = ContextCompat.checkSelfPermission(this, Manifest.permission.READ_CONTACTS) ==
            PackageManager.PERMISSION_GRANTED
        val enrolled = prefs.isEnrolled

        when {
            !enrolled -> {
                statusHeader.setText(R.string.header_setup)
                statusSub.setText(R.string.sub_setup)
            }
            !smsOk -> {
                statusHeader.setText(R.string.header_setup)
                statusSub.setText(R.string.perm_sms_missing)
            }
            !prefs.enabled -> {
                statusHeader.setText(R.string.header_paused)
                statusSub.setText(R.string.sub_paused)
            }
            else -> {
                statusHeader.setText(R.string.header_ready)
                statusSub.setText(R.string.sub_ready)
            }
        }

        enabledSwitch.visibility = if (enrolled) View.VISIBLE else View.GONE
        enabledSwitch.isChecked = prefs.enabled

        lastPull.visibility = if (enrolled) View.VISIBLE else View.GONE
        lastPull.text = if (prefs.lastPullAt > 0) {
            getString(R.string.last_pull, DateUtils.getRelativeTimeSpanString(prefs.lastPullAt), prefs.lastPullCount)
        } else {
            getString(R.string.last_pull_never)
        }
        val err = prefs.lastError
        lastError.visibility = if (err != null) View.VISIBLE else View.GONE
        lastError.text = err?.let { getString(R.string.last_error, it.take(300)) }

        permSms.setText(if (smsOk) R.string.perm_sms_ok else R.string.perm_sms_missing)
        permContacts.setText(if (contactsOk) R.string.perm_contacts_ok else R.string.perm_contacts_missing)
        btnGrant.visibility = if (smsOk && contactsOk) View.GONE else View.VISIBLE

        enrollBlock.visibility = if (enrolled) View.GONE else View.VISIBLE
        manageBlock.visibility = if (enrolled) View.VISIBLE else View.GONE
        val who = prefs.controllerLabel
        sharingWith.text = if (who != null) getString(R.string.sharing_with, who) else getString(R.string.sharing_generic)

        val pm = getSystemService(PowerManager::class.java)
        val hibernationOff = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) packageManager.isAutoRevokeWhitelisted else true
        hibernation.setText(if (hibernationOff) R.string.hibernation_ok else R.string.hibernation_on)
        findViewById<Button>(R.id.btnBattery).visibility =
            if (pm.isIgnoringBatteryOptimizations(packageName)) View.GONE else View.VISIBLE
    }

    companion object {
        private const val SHARING_NOTICE_ID = 8
    }
}
