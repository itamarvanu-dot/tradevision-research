package com.itamar.smsbridge

import android.content.Context
import android.os.Build
import com.google.android.gms.tasks.Tasks
import com.google.firebase.messaging.FirebaseMessaging
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * One-time setup and the encrypted record the iPhone reads to find this phone.
 *
 * Everything here is blocking network work; call it off the main thread.
 */
object Pairing {

    class SetupError(message: String) : Exception(message)

    /** Outcome of picking files: which of the two kinds were recognised. */
    data class Imported(val serviceAccount: ServiceAccount?, val firebase: FirebaseConfig?)

    fun classify(texts: List<String>, packageName: String): Imported {
        var sa: ServiceAccount? = null
        var fb: FirebaseConfig? = null
        for (text in texts) {
            val json = try { JSONObject(text) } catch (_: Exception) { continue }
            when {
                ServiceAccount.isServiceAccount(json) -> sa = ServiceAccount.parse(json)
                FirebaseConfig.isGoogleServices(json) -> fb = FirebaseConfig.fromGoogleServices(json, packageName)
            }
        }
        return Imported(sa, fb)
    }

    /**
     * Takes the project from "key file picked" to "QR ready": registers the app in Firebase
     * if needed, creates and locks down the database, gets this phone's push token and
     * publishes the setup record. Safe to run again; it picks up where it stopped.
     *
     * @return true when done; false when the process has to restart to apply a new project.
     */
    fun run(context: Context, imported: Imported, progress: (Int) -> Unit): Boolean {
        val prefs = Prefs(context)
        val sa = imported.serviceAccount ?: prefs.serviceAccount
            ?: throw SetupError(context.getString(R.string.err_need_key))

        if (imported.firebase != null && imported.firebase.projectId != sa.projectId) {
            throw SetupError(context.getString(R.string.err_project_mismatch))
        }
        if (prefs.serviceAccount?.projectId != sa.projectId) {
            // A different project: nothing from the old one is valid any more.
            prefs.clearAccessToken()
            prefs.firebase = null
            prefs.publishedToken = null
            prefs.fcmToken = null
        }
        prefs.serviceAccount = sa
        val google = Google(sa, prefs.tokenCache)

        progress(R.string.step_auth)
        try {
            google.accessToken()
        } catch (e: Exception) {
            throw SetupError(context.getString(R.string.err_key_rejected) + "\n" + e.message)
        }

        progress(R.string.step_app)
        var config = imported.firebase ?: prefs.firebase ?: try {
            google.androidAppConfig(context.packageName)
        } catch (e: Exception) {
            throw SetupError(context.getString(R.string.err_need_google_services) + "\n" + e.message)
        }

        progress(R.string.step_db)
        if (config.databaseUrl == null) {
            val url = try {
                google.ensureDatabase()
            } catch (e: Exception) {
                throw SetupError(context.getString(R.string.err_db) + "\n" + e.message)
            }
            config = config.copy(databaseUrl = url)
        }
        val dbUrl = config.databaseUrl!!
        try {
            google.setRules(dbUrl, Google.RULES)
        } catch (e: Exception) {
            throw SetupError(context.getString(R.string.err_rules) + "\n" + e.message)
        }

        prefs.firebase = config
        if (!App.initFirebase(context)) return false

        progress(R.string.step_token)
        val token = try {
            Tasks.await(FirebaseMessaging.getInstance().token, 30, TimeUnit.SECONDS)
        } catch (e: Exception) {
            throw SetupError(context.getString(R.string.err_fcm) + "\n" + e.message)
        }
        prefs.fcmToken = token

        if (prefs.boxId == null || prefs.boxKey == null) {
            prefs.boxId = Crypto.newId()
            prefs.boxKey = Crypto.newKey()
        }

        progress(R.string.step_publish)
        publish(context)
        return true
    }

    /**
     * Writes the encrypted setup record: the service-account key and this phone's push token.
     * Re-run whenever the token rotates, so the iPhone always wakes the right device.
     */
    fun publish(context: Context) {
        val prefs = Prefs(context)
        val sa = prefs.serviceAccount ?: return
        val db = prefs.firebase?.databaseUrl ?: return
        val box = prefs.boxId ?: return
        val key = prefs.boxKey ?: return
        val token = prefs.fcmToken ?: return

        val inner = JSONObject()
            .put("sa", sa.toJson())
            .put("fcm", token)
            .put("device", Build.MANUFACTURER.replaceFirstChar { it.uppercase() } + " " + Build.MODEL)
            .put("updated", System.currentTimeMillis())
        val sealed = Crypto.seal(key, inner.toString())
        Google(sa, prefs.tokenCache).dbPut(
            db,
            "boxes/$box/setup",
            JSONObject().put("v", 1).put("iv", sealed.iv).put("ct", sealed.ct),
        )
        prefs.publishedToken = token
    }

    /** New box and key: the old pairing link stops working at once. */
    fun rotate(context: Context) {
        val prefs = Prefs(context)
        val oldBox = prefs.boxId
        prefs.boxId = Crypto.newId()
        prefs.boxKey = Crypto.newKey()
        prefs.publishedToken = null
        publish(context)
        val db = prefs.firebase?.databaseUrl
        if (oldBox != null && db != null) {
            try { prefs.google()?.dbDelete(db, "boxes/$oldBox") } catch (_: Exception) { /* best effort */ }
        }
    }

    /** Sends a pull to this very phone: proves the whole push → read → upload chain works. */
    fun selfTest(context: Context): Boolean {
        val prefs = Prefs(context)
        val google = prefs.google() ?: return false
        val token = prefs.fcmToken ?: return false
        val before = prefs.lastPullAt
        google.sendPush(token, mapOf("t" to "pull", "req" to "selftest-" + Crypto.newId(6), "min" to "60", "lim" to "5"))
        val deadline = System.currentTimeMillis() + 20_000
        while (System.currentTimeMillis() < deadline) {
            Thread.sleep(500)
            if (prefs.lastPullAt > before) return true
        }
        return false
    }
}
