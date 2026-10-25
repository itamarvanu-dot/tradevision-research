package com.itamar.smsbridge

import android.Manifest
import android.annotation.SuppressLint
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.text.format.DateUtils
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.SwitchCompat
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
    private lateinit var fbStatus: TextView
    private lateinit var btnImport: Button
    private lateinit var btnRetry: Button
    private lateinit var setupProgress: TextView
    private lateinit var pairBlock: View
    private lateinit var qrImage: ImageView
    private lateinit var pageUrl: EditText
    private lateinit var btnSelfTest: Button
    private lateinit var selfTestResult: TextView
    private lateinit var hibernation: TextView

    private var busy = false
    private var renderedQr: String? = null

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { render() }

    private val fileLauncher = registerForActivityResult(
        ActivityResultContracts.OpenMultipleDocuments()
    ) { uris -> if (uris.isNotEmpty()) importFiles(uris) }

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
        fbStatus = findViewById(R.id.fbStatus)
        btnImport = findViewById(R.id.btnImport)
        btnRetry = findViewById(R.id.btnRetry)
        setupProgress = findViewById(R.id.setupProgress)
        pairBlock = findViewById(R.id.pairBlock)
        qrImage = findViewById(R.id.qrImage)
        pageUrl = findViewById(R.id.pageUrl)
        btnSelfTest = findViewById(R.id.btnSelfTest)
        selfTestResult = findViewById(R.id.selfTestResult)
        hibernation = findViewById(R.id.hibernation)

        enabledSwitch.isChecked = prefs.enabled
        enabledSwitch.setOnCheckedChangeListener { _, checked ->
            prefs.enabled = checked
            render()
        }

        findViewById<Button>(R.id.btnGrant).setOnClickListener { requestPermissions() }
        btnImport.setOnClickListener { fileLauncher.launch(arrayOf("application/json", "application/octet-stream", "text/plain", "*/*")) }
        btnRetry.setOnClickListener { runSetup(Pairing.Imported(null, null)) }
        findViewById<Button>(R.id.btnShare).setOnClickListener { share() }
        findViewById<Button>(R.id.btnCopy).setOnClickListener { copy() }
        findViewById<Button>(R.id.btnRotate).setOnClickListener { confirmRotate() }
        btnSelfTest.setOnClickListener { selfTest() }
        findViewById<Button>(R.id.btnAppSettings).setOnClickListener { openAppSettings() }
        findViewById<Button>(R.id.btnBattery).setOnClickListener { requestUnrestrictedBattery() }

        pageUrl.setText(prefs.pageUrl)
        pageUrl.setOnFocusChangeListener { _, focused ->
            if (!focused) savePageUrl()
        }
    }

    override fun onResume() {
        super.onResume()
        render()
        // A token that rotated while the app was closed and could not be republished then.
        if (prefs.fcmToken != null && prefs.publishedToken != null && prefs.fcmToken != prefs.publishedToken) {
            background { Pairing.publish(this) }
        }
    }

    override fun onPause() {
        savePageUrl()
        super.onPause()
    }

    // ------------------------------------------------------------- Actions

    private fun requestPermissions() {
        val wanted = mutableListOf(Manifest.permission.READ_SMS, Manifest.permission.READ_CONTACTS)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            wanted.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        permissionLauncher.launch(wanted.toTypedArray())
    }

    private fun importFiles(uris: List<Uri>) {
        val texts = uris.mapNotNull { uri ->
            try {
                contentResolver.openInputStream(uri)?.use { it.readBytes() }
                    ?.takeIf { it.size < 64 * 1024 }
                    ?.toString(Charsets.UTF_8)
            } catch (_: Exception) {
                null
            }
        }
        val imported = try {
            Pairing.classify(texts, packageName)
        } catch (e: Exception) {
            showSetupMessage(e.message ?: getString(R.string.err_unknown_files), error = true)
            return
        }
        if (imported.serviceAccount == null && imported.firebase == null) {
            showSetupMessage(getString(R.string.err_unknown_files), error = true)
            return
        }
        runSetup(imported)
    }

    private fun runSetup(imported: Pairing.Imported) {
        if (busy) return
        busy = true
        render()
        showSetupMessage(getString(R.string.working), error = false)
        thread(name = "setup") {
            val result: Result<Boolean> = runCatching {
                Pairing.run(this, imported) { step -> runOnUiThread { showSetupMessage(getString(step), false) } }
            }
            runOnUiThread {
                busy = false
                result.onSuccess { done ->
                    if (done) {
                        showSetupMessage(getString(R.string.setup_done), error = false)
                    } else {
                        restartForNewProject()
                    }
                }.onFailure { e ->
                    showSetupMessage(e.message ?: e.toString(), error = true)
                }
                render()
            }
        }
    }

    /** Firebase cannot switch projects inside a running process; start a fresh one. */
    private fun restartForNewProject() {
        Toast.makeText(this, R.string.restarting, Toast.LENGTH_LONG).show()
        val intent = packageManager.getLaunchIntentForPackage(packageName)!!
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        startActivity(intent)
        exitProcess(0)
    }

    private fun selfTest() {
        if (busy) return
        busy = true
        btnSelfTest.isEnabled = false
        selfTestResult.text = getString(R.string.selftest_running)
        thread(name = "selftest") {
            val result = runCatching { Pairing.selfTest(this) }
            runOnUiThread {
                busy = false
                btnSelfTest.isEnabled = true
                selfTestResult.text = when {
                    result.getOrNull() == true -> getString(R.string.selftest_ok)
                    else -> getString(R.string.selftest_fail, result.exceptionOrNull()?.message ?: prefs.lastError ?: "")
                }
                render()
            }
        }
    }

    private fun confirmRotate() {
        AlertDialog.Builder(this)
            .setMessage(R.string.rotate_confirm)
            .setPositiveButton(android.R.string.ok) { _, _ -> background { Pairing.rotate(this) } }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun share() {
        val url = prefs.pairingUrl() ?: return
        startActivity(
            Intent.createChooser(
                Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, url),
                getString(R.string.btn_share),
            )
        )
    }

    private fun copy() {
        val url = prefs.pairingUrl() ?: return
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.setPrimaryClip(ClipData.newPlainText("SMS Bridge", url))
        Toast.makeText(this, R.string.copied, Toast.LENGTH_SHORT).show()
    }

    private fun savePageUrl() {
        var url = pageUrl.text.toString().trim()
        if (url.isEmpty()) url = BuildConfig.DEFAULT_PAGE_URL
        if (!url.startsWith("https://")) return
        if (url != prefs.pageUrl) {
            prefs.pageUrl = url
            render()
        }
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

    // --------------------------------------------------------------- View

    private fun showSetupMessage(text: String, error: Boolean) {
        setupProgress.visibility = View.VISIBLE
        setupProgress.text = text
        setupProgress.setTextColor(if (error) 0xFFE53935.toInt() else statusSub.currentTextColor)
    }

    private fun render() {
        val smsOk = SmsRepository.hasSmsPermission(this)
        val contactsOk = ContextCompat.checkSelfPermission(this, Manifest.permission.READ_CONTACTS) ==
            android.content.pm.PackageManager.PERMISSION_GRANTED
        val paired = prefs.isPaired

        when {
            !paired || !smsOk -> {
                statusHeader.setText(R.string.header_setup)
                statusSub.setText(R.string.sub_setup)
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
        enabledSwitch.visibility = if (paired) View.VISIBLE else View.GONE

        lastPull.text = if (prefs.lastPullAt > 0) {
            getString(
                R.string.last_pull,
                DateUtils.getRelativeTimeSpanString(prefs.lastPullAt),
                prefs.lastPullCount,
            )
        } else {
            getString(R.string.last_pull_never)
        }
        val err = prefs.lastError
        lastError.visibility = if (err != null) View.VISIBLE else View.GONE
        lastError.text = err?.let { getString(R.string.last_error, it.take(200)) }

        permSms.setText(if (smsOk) R.string.perm_sms_ok else R.string.perm_sms_missing)
        permContacts.setText(if (contactsOk) R.string.perm_contacts_ok else R.string.perm_contacts_missing)

        val project = prefs.serviceAccount?.projectId
        fbStatus.text = if (project != null) getString(R.string.fb_connected, project) else getString(R.string.fb_none)
        btnImport.isEnabled = !busy
        btnRetry.visibility = if (project != null && !paired && !busy) View.VISIBLE else View.GONE

        pairBlock.visibility = if (paired) View.VISIBLE else View.GONE
        val url = prefs.pairingUrl()
        if (paired && url != null && url != renderedQr) {
            qrImage.setImageBitmap(Qr.bitmap(url, 720))
            renderedQr = url
        }

        val pm = getSystemService(PowerManager::class.java)
        val hibernationOff = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            packageManager.isAutoRevokeWhitelisted
        } else {
            true
        }
        hibernation.setText(if (hibernationOff) R.string.hibernation_ok else R.string.hibernation_on)
        findViewById<Button>(R.id.btnBattery).visibility =
            if (pm.isIgnoringBatteryOptimizations(packageName)) View.GONE else View.VISIBLE
    }
}
