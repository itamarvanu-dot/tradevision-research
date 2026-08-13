package com.itamar.smsbridge

import android.content.Context
import android.os.Build
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * A deliberately tiny HTTP/1.1 server. It only has to answer GET from one phone on the
 * same network, so it carries no dependency beyond the Android framework.
 *
 * It serves two things:
 *   - the web UI from `assets/web` (unauthenticated — it is an empty shell)
 *   - the API routes, which require the access token and are where messages leave the device
 *
 * Protocol details live in [HttpUtil] so they can be unit tested off-device.
 */
class HttpServer(
    private val context: Context,
    private val port: Int,
    private val tokenProvider: () -> String,
    private val onApiRequest: () -> Unit,
) {

    private val pool = Executors.newFixedThreadPool(4)
    private var serverSocket: ServerSocket? = null

    @Volatile private var running = false

    private val failedAuthCount = AtomicInteger(0)
    @Volatile private var lockedOutUntil = 0L

    /** Throws [IOException] when the port is already taken, so the caller can report it. */
    fun start() {
        if (running) return
        val socket = ServerSocket()
        socket.reuseAddress = true
        socket.bind(InetSocketAddress(port), BACKLOG)
        serverSocket = socket
        running = true

        Thread({ acceptLoop(socket) }, "sms-bridge-accept").apply {
            isDaemon = true
            start()
        }
    }

    /** False once the listening socket has died, which is what the service watchdog checks. */
    fun isListening(): Boolean {
        val socket = serverSocket
        return running && socket != null && socket.isBound && !socket.isClosed
    }

    fun stop() {
        running = false
        try {
            serverSocket?.close()
        } catch (_: IOException) {
            // Closing the socket is what breaks the accept loop; a failure here is not actionable.
        }
        serverSocket = null
        pool.shutdownNow()
        try {
            pool.awaitTermination(2, TimeUnit.SECONDS)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
        }
    }

    private fun acceptLoop(socket: ServerSocket) {
        while (running) {
            try {
                val client = socket.accept()
                try {
                    pool.execute { serve(client) }
                } catch (_: RejectedExecutionException) {
                    client.close()
                }
            } catch (e: IOException) {
                if (running) Log.w(TAG, "accept failed", e)
            }
        }
    }

    private fun serve(client: Socket) {
        try {
            client.soTimeout = SOCKET_TIMEOUT_MS
            client.getInputStream().buffered().use { input ->
                client.getOutputStream().buffered().use { output ->
                    val request = HttpUtil.readRequest(input)
                    if (request == null) {
                        respond(output, 400, "text/plain; charset=utf-8", BAD_REQUEST, false)
                    } else {
                        handle(request, output)
                    }
                    output.flush()
                }
            }
        } catch (e: Exception) {
            Log.d(TAG, "request failed: ${e.message}")
        } finally {
            try {
                client.close()
            } catch (_: IOException) {
                // Already closed.
            }
        }
    }

    private fun handle(request: HttpUtil.Request, output: OutputStream) {
        // HEAD gets the same headers as GET but no body, per the spec.
        val withBody = request.method != "HEAD"
        if (request.method != "GET" && request.method != "HEAD") {
            respond(output, 405, "text/plain; charset=utf-8", METHOD_NOT_ALLOWED, withBody)
            return
        }
        if (request.path.startsWith("/api/")) {
            handleApi(request, output, withBody)
        } else {
            handleStatic(request.path, output, withBody)
        }
    }

    // ---------------------------------------------------------------- API

    private fun handleApi(request: HttpUtil.Request, output: OutputStream, withBody: Boolean) {
        // Unauthenticated liveness probe, so the web UI can tell "wrong address" from "wrong token".
        if (request.path == "/api/ping") {
            respondJson(output, 200, JSONObject().put("ok", true).put("app", "sms-bridge"), withBody)
            return
        }

        val now = System.currentTimeMillis()
        if (now < lockedOutUntil) {
            respondJson(
                output,
                429,
                JSONObject()
                    .put("ok", false)
                    .put("error", "locked")
                    .put("retryAfterSeconds", (lockedOutUntil - now) / 1000),
                withBody,
            )
            return
        }

        if (!HttpUtil.constantTimeEquals(HttpUtil.tokenFrom(request), tokenProvider())) {
            if (failedAuthCount.incrementAndGet() >= MAX_FAILED_AUTH) {
                failedAuthCount.set(0)
                lockedOutUntil = now + LOCKOUT_MS
                Log.w(TAG, "too many bad tokens — locking the API for ${LOCKOUT_MS / 1000}s")
            }
            respondJson(output, 401, JSONObject().put("ok", false).put("error", "bad_token"), withBody)
            return
        }
        failedAuthCount.set(0)
        onApiRequest()

        when (request.path) {
            "/api/messages" -> respondJson(output, 200, messagesPayload(request.query), withBody)
            "/api/info" -> respondJson(output, 200, infoPayload(), withBody)
            else -> respondJson(
                output,
                404,
                JSONObject().put("ok", false).put("error", "not_found"),
                withBody,
            )
        }
    }

    private fun messagesPayload(query: Map<String, String>): JSONObject {
        if (!SmsRepository.hasSmsPermission(context)) {
            return JSONObject()
                .put("ok", false)
                .put("error", "no_sms_permission")
                .put("message", context.getString(R.string.api_no_sms_permission))
        }

        val messages = SmsRepository.query(
            context = context,
            limit = query["limit"]?.toIntOrNull() ?: DEFAULT_LIMIT,
            since = query["since"]?.toLongOrNull() ?: 0L,
            search = query["q"],
        )

        val array = JSONArray()
        for (m in messages) {
            array.put(
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
            .put("ok", true)
            .put("now", System.currentTimeMillis())
            .put("count", array.length())
            .put("messages", array)
    }

    private fun infoPayload(): JSONObject = JSONObject()
        .put("ok", true)
        .put("device", "${Build.MANUFACTURER} ${Build.MODEL}")
        .put("android", Build.VERSION.RELEASE)
        .put("now", System.currentTimeMillis())
        .put("hasSmsPermission", SmsRepository.hasSmsPermission(context))
        .put("inboxCount", SmsRepository.totalCount(context))

    // ------------------------------------------------------------- Static

    private fun handleStatic(path: String, output: OutputStream, withBody: Boolean) {
        val name = HttpUtil.assetNameFor(path)
        if (name == null) {
            respond(output, 404, "text/plain; charset=utf-8", NOT_FOUND, withBody)
            return
        }
        val bytes = try {
            context.assets.open("web/$name").use { it.readBytes() }
        } catch (_: IOException) {
            respond(output, 404, "text/plain; charset=utf-8", NOT_FOUND, withBody)
            return
        }
        respond(output, 200, HttpUtil.contentTypeFor(name), bytes, withBody)
    }

    // ------------------------------------------------------------ Plumbing

    private fun respondJson(output: OutputStream, status: Int, body: JSONObject, withBody: Boolean) {
        respond(
            output,
            status,
            "application/json; charset=utf-8",
            body.toString().toByteArray(),
            withBody,
        )
    }

    private fun respond(
        output: OutputStream,
        status: Int,
        contentType: String,
        body: ByteArray,
        withBody: Boolean,
    ) {
        output.write(HttpUtil.headerBlock(status, contentType, body.size).toByteArray(Charsets.US_ASCII))
        if (withBody) output.write(body)
    }

    companion object {
        private const val TAG = "SmsBridgeHttp"
        private const val BACKLOG = 16
        private const val SOCKET_TIMEOUT_MS = 15_000
        private const val DEFAULT_LIMIT = 200
        private const val MAX_FAILED_AUTH = 10
        private const val LOCKOUT_MS = 5 * 60 * 1000L

        private val NOT_FOUND = "Not Found".toByteArray()
        private val BAD_REQUEST = "Bad Request".toByteArray()
        private val METHOD_NOT_ALLOWED = "Method Not Allowed".toByteArray()
    }
}
