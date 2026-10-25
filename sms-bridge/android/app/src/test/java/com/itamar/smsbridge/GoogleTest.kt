package com.itamar.smsbridge

import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.net.URLDecoder
import java.security.KeyPairGenerator
import java.security.Signature
import java.util.Base64
import java.util.zip.GZIPInputStream

/** Runs the real request code against a local fake of the Google endpoints. */
class GoogleTest {

    private data class Call(val method: String, val path: String, val query: String?, val headers: Map<String, String>, val body: ByteArray)

    private val keyPair = KeyPairGenerator.getInstance("RSA").apply { initialize(2048) }.generateKeyPair()
    private val server = MockWebServer()
    private lateinit var base: String
    private val calls = mutableListOf<Call>()
    private var handler: (Call) -> Pair<Int, String> = { 404 to "{}" }

    @Before
    fun start() {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val url = request.requestUrl!!
                val call = Call(
                    request.method!!,
                    url.encodedPath,
                    url.encodedQuery,
                    request.headers.toMultimap().mapValues { it.value.first() }.mapKeys { it.key.lowercase() },
                    request.body.readByteArray(),
                )
                synchronized(calls) { calls.add(call) }
                val (code, body) = handler(call)
                return MockResponse().setResponseCode(code).setBody(body)
            }
        }
        server.start()
        base = server.url("/").toString().trimEnd('/')
    }

    @After
    fun stop() = server.shutdown()

    private fun google(): Google {
        val pem = "-----BEGIN PRIVATE KEY-----\n" +
            Base64.getMimeEncoder().encodeToString(keyPair.private.encoded) + "\n-----END PRIVATE KEY-----\n"
        val sa = ServiceAccount("proj", "sa@proj.iam.gserviceaccount.com", pem, "$base/token")
        return Google(sa, null, Google.Endpoints(base, base, base, base))
    }

    private fun tokenEndpoint(call: Call): Pair<Int, String>? {
        if (call.path != "/token") return null
        val form = String(call.body).split("&").associate {
            val (k, v) = it.split("=", limit = 2); k to URLDecoder.decode(v, "UTF-8")
        }
        val parts = form.getValue("assertion").split(".")
        val ok = Signature.getInstance("SHA256withRSA").run {
            initVerify(keyPair.public)
            update("${parts[0]}.${parts[1]}".toByteArray())
            verify(Crypto.unb64url(parts[2]))
        }
        return if (ok && form["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer") {
            200 to """{"access_token":"AT","expires_in":3600}"""
        } else {
            400 to """{"error":"invalid_grant"}"""
        }
    }

    @Test
    fun `database writes carry the token as access_token`() {
        handler = { c -> tokenEndpoint(c) ?: (200 to "null") }
        google().dbPut(base, "boxes/b1/inbox", JSONObject().put("req", "r"))
        val put = calls.single { it.method == "PUT" }
        assertEquals("/boxes/b1/inbox.json", put.path)
        assertEquals("access_token=AT", put.query)
        assertEquals("r", JSONObject(String(put.body)).getString("req"))
    }

    @Test
    fun `rules go to settings with the locked-down document`() {
        handler = { c -> tokenEndpoint(c) ?: (200 to "{}") }
        google().setRules(base, Google.RULES)
        val put = calls.single { it.method == "PUT" }
        assertEquals("/.settings/rules.json", put.path)
        val rules = JSONObject(String(put.body)).getJSONObject("rules")
        assertEquals(false, rules.getBoolean(".read"))
        assertEquals(true, rules.getJSONObject("boxes").getJSONObject("\$box").getJSONObject("setup").getBoolean(".read"))
    }

    @Test
    fun `push is high priority, data only, with bearer auth`() {
        handler = { c -> tokenEndpoint(c) ?: (200 to """{"name":"m"}""") }
        google().sendPush("TOKEN", mapOf("t" to "pull", "req" to "r1"))
        val send = calls.single { it.path.endsWith("messages:send") }
        assertEquals("/v1/projects/proj/messages:send", send.path)
        assertEquals("Bearer AT", send.headers["authorization"])
        val msg = JSONObject(String(send.body)).getJSONObject("message")
        assertEquals("TOKEN", msg.getString("token"))
        assertEquals("HIGH", msg.getJSONObject("android").getString("priority"))
        assertEquals("pull", msg.getJSONObject("data").getString("t"))
        assertTrue(!msg.has("notification"))
    }

    @Test
    fun `access token is cached between calls`() {
        handler = { c -> tokenEndpoint(c) ?: (200 to "null") }
        val g = Google(
            ServiceAccount("proj", "sa@x", "-----BEGIN PRIVATE KEY-----\n" +
                Base64.getMimeEncoder().encodeToString(keyPair.private.encoded) + "\n-----END PRIVATE KEY-----", "$base/token"),
            object : Google.TokenCache {
                var v: Pair<String, Long>? = null
                override fun load() = v
                override fun store(token: String, expiresAtMs: Long) { v = token to expiresAtMs }
            },
            Google.Endpoints(base, base, base, base),
        )
        g.dbPut(base, "a", "1")
        g.dbPut(base, "b", "2")
        assertEquals(1, calls.count { it.path == "/token" })
    }

    @Test
    fun `database is created when the project has none`() {
        handler = { c ->
            tokenEndpoint(c) ?: when {
                c.method == "GET" && c.path.endsWith("/locations/-/instances") -> 200 to "{}"
                c.method == "POST" && c.path.endsWith("/locations/us-central1/instances") ->
                    200 to """{"databaseUrl":"https://proj-default-rtdb.firebaseio.com"}"""
                else -> 404 to "{}"
            }
        }
        assertEquals("https://proj-default-rtdb.firebaseio.com", google().ensureDatabase())
        val create = calls.single { it.method == "POST" && it.path.contains("instances") }
        assertEquals("databaseId=proj-default-rtdb", create.query)
        assertEquals("DEFAULT_DATABASE", JSONObject(String(create.body)).getString("type"))
    }

    @Test
    fun `android app is registered and its config read back`() {
        val gs = JSONObject("""{"project_info":{"project_number":"42","project_id":"proj"},
            "client":[{"client_info":{"mobilesdk_app_id":"1:42:android:x","android_client_info":{"package_name":"com.itamar.smsbridge"}},
            "api_key":[{"current_key":"KEY"}]}]}""")
        handler = { c ->
            tokenEndpoint(c) ?: when {
                c.method == "GET" && c.path == "/v1beta1/projects/proj/androidApps" -> 200 to "{}"
                c.method == "POST" && c.path == "/v1beta1/projects/proj/androidApps" -> 200 to """{"name":"operations/op1","done":false}"""
                c.path == "/v1beta1/operations/op1" -> 200 to """{"name":"operations/op1","done":true,"response":{"appId":"1:42:android:x"}}"""
                c.path == "/v1beta1/projects/proj/androidApps/1:42:android:x/config" ->
                    200 to JSONObject().put("configFileContents", Base64.getEncoder().encodeToString(gs.toString().toByteArray())).toString()
                else -> 404 to "{}"
            }
        }
        val config = google().androidAppConfig("com.itamar.smsbridge")
        assertEquals("1:42:android:x", config.appId)
        assertEquals("KEY", config.apiKey)
        assertEquals("42", config.senderId)
    }

    @Test
    fun `page deploy runs the full hosting sequence`() {
        val html = "<html>page</html>".toByteArray()
        var uploaded: ByteArray? = null
        handler = { c ->
            tokenEndpoint(c) ?: when {
                c.method == "GET" && c.path == "/v1beta1/projects/proj/sites" -> 200 to "{}"
                c.method == "POST" && c.path == "/v1beta1/projects/proj/sites" ->
                    200 to """{"name":"projects/proj/sites/proj","defaultUrl":"https://proj.web.app","type":"DEFAULT_SITE"}"""
                c.method == "POST" && c.path == "/v1beta1/sites/proj/versions" -> 200 to """{"name":"sites/proj/versions/v1"}"""
                c.path == "/v1beta1/sites/proj/versions/v1:populateFiles" -> {
                    val hash = JSONObject(String(c.body)).getJSONObject("files").getString("/index.html")
                    200 to """{"uploadRequiredHashes":["$hash"],"uploadUrl":"$base/upload/sites/proj/versions/v1/files"}"""
                }
                c.path.startsWith("/upload/") -> { uploaded = c.body; 200 to "" }
                c.path == "/v1beta1/sites/proj/versions/v1" -> 200 to "{}"
                c.method == "POST" && c.path == "/v1beta1/sites/proj/releases" -> 200 to "{}"
                else -> 404 to "{}"
            }
        }
        assertEquals("https://proj.web.app/", google().deployPage(html))

        assertEquals(String(html), String(GZIPInputStream(uploaded!!.inputStream()).readBytes()))
        val finalize = calls.single { it.path == "/v1beta1/sites/proj/versions/v1" }
        assertEquals("POST", finalize.method)
        assertEquals("PATCH", finalize.headers["x-http-method-override"])
        assertEquals("update_mask=status", finalize.query)
        assertEquals("FINALIZED", JSONObject(String(finalize.body)).getString("status"))
        val release = calls.single { it.path.endsWith("/releases") }
        assertEquals("versionName=sites%2Fproj%2Fversions%2Fv1", release.query)
        // Order matters to the Hosting API.
        val order = calls.filter { it.path != "/token" }
            .map { if (it.path.startsWith("/upload/")) "upload" else it.path.substringAfterLast('/') }
        assertEquals(listOf("sites", "sites", "versions", "v1:populateFiles", "upload", "v1", "releases"), order)
        // The file is uploaded under its own hash, as populateFiles asked.
        val upload = calls.single { it.path.startsWith("/upload/") }
        assertTrue(upload.path.endsWith("/files/" + JSONObject(String(calls.single { it.path.endsWith(":populateFiles") }.body))
            .getJSONObject("files").getString("/index.html")))
    }

    @Test(expected = Google.HttpError::class)
    fun `http errors surface with their status`() {
        handler = { c -> tokenEndpoint(c) ?: (403 to """{"error":{"status":"PERMISSION_DENIED"}}""") }
        google().ensureDatabase()
    }
}
