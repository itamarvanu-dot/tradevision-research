package com.itamar.smsbridge

import android.content.Context
import android.os.Build
import com.google.android.gms.tasks.Tasks
import com.google.firebase.messaging.FirebaseMessaging
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/** The public Firebase values the sender needs. None of these is a secret. */
data class PublicConfig(
    val projectId: String,
    val appId: String,
    val apiKey: String,
    val senderId: String,
    val databaseUrl: String,
)

/**
 * Everything the controller (the iPhone) hands this phone in the enrollment link:
 * the public project config, this phone's own box (a secret path in the database),
 * the AES key shared only between the two devices, and a name for the controller so
 * the owner of this phone can see who their messages go to.
 */
data class Enrollment(
    val config: PublicConfig,
    val boxId: String,
    val boxKey: String,
    val controllerLabel: String?,
) {
    companion object {
        /** Accepts a smsbridge://enroll?e=<code> link, a full URL with ?e=/#e=, or the bare code. */
        fun parse(input: String): Enrollment? {
            val raw = input.trim()
            val code = extractCode(raw) ?: return null
            return try {
                val j = JSONObject(String(Crypto.unb64url(code), Charsets.UTF_8))
                val db = j.getString("d")
                require(db.startsWith("https://"))
                Enrollment(
                    config = PublicConfig(
                        projectId = j.getString("p"),
                        appId = j.getString("a"),
                        apiKey = j.getString("k"),
                        senderId = j.getString("s"),
                        databaseUrl = db,
                    ),
                    boxId = j.getString("b"),
                    boxKey = j.getString("x"),
                    controllerLabel = j.optString("n").ifBlank { null },
                )
            } catch (_: Exception) {
                null
            }
        }

        private fun extractCode(raw: String): String? {
            // A full bare code with no delimiters.
            if (!raw.contains("://") && !raw.contains("e=") && raw.matches(Regex("[A-Za-z0-9_-]{20,}"))) return raw
            // Otherwise the code rides in an "e=" parameter, in the query or the fragment of a link.
            return Regex("[?&#]e=([A-Za-z0-9_-]+)").find(raw)?.groupValues?.get(1)
        }
    }
}

object Enroller {

    class EnrollError(message: String) : Exception(message)

    /**
     * Stores the enrollment, registers this phone for pushes and publishes its (encrypted)
     * setup record so the controller can reach it. Blocking; call off the main thread.
     *
     * @return false when the project changed and the process must restart to apply it.
     */
    fun enroll(context: Context, e: Enrollment, progress: (Int) -> Unit): Boolean {
        val prefs = Prefs(context)
        val sameProject = prefs.config?.projectId == e.config.projectId &&
            prefs.config?.appId == e.config.appId

        prefs.config = e.config
        prefs.boxId = e.boxId
        prefs.boxKey = e.boxKey
        prefs.controllerLabel = e.controllerLabel
        prefs.publishedToken = null
        if (!sameProject) prefs.fcmToken = null

        if (!App.initFirebase(context)) return false

        progress(R.string.step_token)
        val token = try {
            Tasks.await(FirebaseMessaging.getInstance().token, 30, TimeUnit.SECONDS)
        } catch (ex: Exception) {
            throw EnrollError(context.getString(R.string.err_fcm) + "\n" + ex.message)
        }
        prefs.fcmToken = token

        progress(R.string.step_publish)
        try {
            publish(context)
        } catch (ex: Net.HttpError) {
            throw EnrollError(
                if (ex.code == 401 || ex.code == 403) context.getString(R.string.err_revoked)
                else context.getString(R.string.err_publish) + "\n" + ex.message
            )
        }
        return true
    }

    /** (Re)writes the encrypted setup record: this phone's push token and model. */
    fun publish(context: Context) {
        val prefs = Prefs(context)
        val db = prefs.config?.databaseUrl ?: return
        val box = prefs.boxId ?: return
        val key = prefs.boxKey ?: return
        val token = prefs.fcmToken ?: return

        val inner = JSONObject()
            .put("fcm", token)
            .put("device", deviceName())
            .put("updated", System.currentTimeMillis())
        val sealed = Crypto.seal(key, inner.toString())
        Net.putJson(
            db,
            "boxes/$box/setup",
            JSONObject().put("v", 1).put("iv", sealed.iv).put("ct", sealed.ct).toString(),
        )
        prefs.publishedToken = token
    }

    fun unenroll(context: Context) {
        Prefs(context).clearEnrollment()
    }

    fun deviceName() = Build.MANUFACTURER.replaceFirstChar { it.uppercase() } + " " + Build.MODEL
}
