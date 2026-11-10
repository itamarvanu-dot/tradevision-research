package com.itamar.smsbridge

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Button
import androidx.appcompat.app.AppCompatActivity

/**
 * Prominent disclosure, shown full screen BEFORE the runtime READ_SMS request
 * (Google Play User Data policy). It says what is read, where it goes, that it is never
 * sold or shared, and how to stop. Only "Agree" leads to the system permission dialog;
 * "Not now" returns without asking for anything.
 */
class DisclosureActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_disclosure)

        findViewById<Button>(R.id.btnAgree).setOnClickListener {
            Prefs(this).smsConsent = true
            setResult(Activity.RESULT_OK)
            finish()
        }
        findViewById<Button>(R.id.btnNotNow).setOnClickListener {
            setResult(Activity.RESULT_CANCELED)
            finish()
        }
        findViewById<Button>(R.id.btnPrivacy).setOnClickListener { openPrivacyPolicy(this) }
    }

    companion object {
        const val PRIVACY_URL =
            "https://itamarvanu-dot.github.io/tradevision-research/sms-bridge/web/privacy.html"

        fun openPrivacyPolicy(activity: Activity) {
            try {
                activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(PRIVACY_URL)))
            } catch (_: Exception) { /* no browser */ }
        }
    }
}
