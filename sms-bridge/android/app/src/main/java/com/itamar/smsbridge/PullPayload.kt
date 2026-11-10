package com.itamar.smsbridge

import org.json.JSONArray
import org.json.JSONObject

/** The reply to one pull, before encryption. Pure, so it is covered by unit tests. */
object PullPayload {

    const val DEFAULT_MINUTES = 60
    const val DEFAULT_LIMIT = 200
    const val MAX_LIMIT = 500

    data class Request(val req: String, val minutes: Int, val limit: Int)

    /** Parses the push data. Returns null for anything that is not a well-formed pull. */
    fun parse(data: Map<String, String>): Request? {
        if (data["t"] != "pull") return null
        val req = data["req"]?.takeIf { it.isNotBlank() && it.length <= 64 } ?: return null
        // minutes = 0 means "no time bound, just the latest [limit]".
        val minutes = data["min"]?.toIntOrNull()?.coerceIn(0, 60 * 24 * 31) ?: DEFAULT_MINUTES
        val limit = data["lim"]?.toIntOrNull()?.coerceIn(1, MAX_LIMIT) ?: DEFAULT_LIMIT
        return Request(req, minutes, limit)
    }

    /** Lower bound for the inbox query, or 0 for none. */
    fun since(request: Request, nowMs: Long): Long =
        if (request.minutes == 0) 0L else nowMs - request.minutes * 60_000L

    fun build(
        request: Request,
        messages: List<SmsRepository.Message>,
        device: String,
        battery: Int?,
        nowMs: Long,
        status: String = "ok",
    ): JSONObject {
        val list = JSONArray()
        for (m in messages) {
            list.put(
                JSONObject()
                    .put("id", m.id)
                    .put("from", m.address)
                    .put("name", m.contactName ?: JSONObject.NULL)
                    .put("body", m.body)
                    .put("date", m.date)
                    .put("read", m.read)
            )
        }
        return JSONObject()
            .put("req", request.req)
            .put("status", status)
            .put("at", nowMs)
            .put("device", device)
            .put("battery", battery ?: JSONObject.NULL)
            .put("min", request.minutes)
            .put("messages", list)
    }
}
