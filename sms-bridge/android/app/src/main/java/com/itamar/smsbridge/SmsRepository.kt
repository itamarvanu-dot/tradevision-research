package com.itamar.smsbridge

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.provider.Telephony
import androidx.core.content.ContextCompat

/** Reads the device SMS inbox. Read-only: nothing here ever writes or deletes a message. */
object SmsRepository {

    data class Message(
        val id: Long,
        val address: String,
        val contactName: String?,
        val body: String,
        val date: Long,
        val read: Boolean,
    )

    private const val MAX_LIMIT = 1000

    /**
     * Newest first.
     *
     * @param limit  how many messages to return, capped at [MAX_LIMIT].
     * @param since  only messages strictly newer than this epoch-millis, or 0 for no bound.
     * @param search free-text matched against both the body and the sender.
     */
    fun query(context: Context, limit: Int, since: Long = 0L, search: String? = null): List<Message> {
        if (!hasSmsPermission(context)) return emptyList()

        val capped = limit.coerceIn(1, MAX_LIMIT)
        val where = StringBuilder()
        val args = mutableListOf<String>()

        if (since > 0L) {
            where.append(Telephony.Sms.DATE).append(" > ?")
            args.add(since.toString())
        }
        if (!search.isNullOrBlank()) {
            if (where.isNotEmpty()) where.append(" AND ")
            where.append("(")
                .append(Telephony.Sms.BODY).append(" LIKE ? OR ")
                .append(Telephony.Sms.ADDRESS).append(" LIKE ?)")
            val pattern = "%${search.trim()}%"
            args.add(pattern)
            args.add(pattern)
        }

        val projection = arrayOf(
            Telephony.Sms._ID,
            Telephony.Sms.ADDRESS,
            Telephony.Sms.BODY,
            Telephony.Sms.DATE,
            Telephony.Sms.READ,
        )

        val cursor = context.contentResolver.query(
            Telephony.Sms.Inbox.CONTENT_URI,
            projection,
            where.toString().ifEmpty { null },
            if (args.isEmpty()) null else args.toTypedArray(),
            "${Telephony.Sms.DATE} DESC LIMIT $capped",
        ) ?: return emptyList()

        val out = ArrayList<Message>(capped)

        cursor.use { c ->
            val idIdx = c.getColumnIndexOrThrow(Telephony.Sms._ID)
            val addressIdx = c.getColumnIndexOrThrow(Telephony.Sms.ADDRESS)
            val bodyIdx = c.getColumnIndexOrThrow(Telephony.Sms.BODY)
            val dateIdx = c.getColumnIndexOrThrow(Telephony.Sms.DATE)
            val readIdx = c.getColumnIndexOrThrow(Telephony.Sms.READ)

            while (c.moveToNext()) {
                val address = c.getString(addressIdx) ?: ""
                out.add(
                    Message(
                        id = c.getLong(idIdx),
                        address = address,
                        // The Play build does not read contacts; the controller shows the sender as sent.
                        contactName = null,
                        body = c.getString(bodyIdx) ?: "",
                        date = c.getLong(dateIdx),
                        read = c.getInt(readIdx) != 0,
                    )
                )
            }
        }
        return out
    }

    fun hasSmsPermission(context: Context): Boolean =
        ContextCompat.checkSelfPermission(context, Manifest.permission.READ_SMS) ==
            PackageManager.PERMISSION_GRANTED
}
