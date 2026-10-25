package com.itamar.smsbridge

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.security.KeyPairGenerator
import java.security.Signature
import java.util.Base64

class ServiceAccountTest {

    private val keyPair = KeyPairGenerator.getInstance("RSA").apply { initialize(2048) }.generateKeyPair()

    private val pem = "-----BEGIN PRIVATE KEY-----\n" +
        Base64.getMimeEncoder(64, "\n".toByteArray()).encodeToString(keyPair.private.encoded) +
        "\n-----END PRIVATE KEY-----\n"

    private val keyFile = JSONObject()
        .put("type", "service_account")
        .put("project_id", "sms-bridge-test")
        .put("private_key_id", "abc")
        .put("private_key", pem)
        .put("client_email", "firebase-adminsdk@sms-bridge-test.iam.gserviceaccount.com")
        .put("token_uri", "https://oauth2.googleapis.com/token")

    @Test
    fun `recognises and parses a service account file`() {
        assertTrue(ServiceAccount.isServiceAccount(keyFile))
        val sa = ServiceAccount.parse(keyFile)
        assertEquals("sms-bridge-test", sa.projectId)
        assertEquals(keyFile.getString("client_email"), sa.clientEmail)
    }

    @Test
    fun `assertion is a valid RS256 JWT with the expected claims`() {
        val sa = ServiceAccount.parse(keyFile)
        val jwt = sa.assertion("scope-a scope-b", 1_700_000_000L)
        val parts = jwt.split(".")
        assertEquals(3, parts.size)

        val header = JSONObject(String(Crypto.unb64url(parts[0])))
        val claims = JSONObject(String(Crypto.unb64url(parts[1])))
        assertEquals("RS256", header.getString("alg"))
        assertEquals(sa.clientEmail, claims.getString("iss"))
        assertEquals("https://oauth2.googleapis.com/token", claims.getString("aud"))
        assertEquals("scope-a scope-b", claims.getString("scope"))
        assertEquals(1_700_003_600L, claims.getLong("exp"))

        val ok = Signature.getInstance("SHA256withRSA").run {
            initVerify(keyPair.public)
            update("${parts[0]}.${parts[1]}".toByteArray())
            verify(Crypto.unb64url(parts[2]))
        }
        assertTrue(ok)
    }

    @Test
    fun `json export keeps only what the iPhone needs`() {
        val exported = ServiceAccount.parse(keyFile).toJson()
        assertEquals(setOf("project_id", "client_email", "private_key", "token_uri"), exported.keySet())
    }
}
