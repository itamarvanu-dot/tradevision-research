package com.itamar.smsbridge

import org.json.JSONObject
import java.security.KeyFactory
import java.security.Signature
import java.security.spec.PKCS8EncodedKeySpec
import java.util.Base64

/**
 * The Firebase project's service-account key. It is what lets the iPhone send the wake-up
 * push and read the reply without any server of our own, and what lets this app set the
 * project up by itself.
 */
data class ServiceAccount(
    val projectId: String,
    val clientEmail: String,
    val privateKeyPem: String,
    val tokenUri: String,
) {

    /** A signed JWT assertion, exchanged at [tokenUri] for an OAuth access token. */
    fun assertion(scopes: String, nowSeconds: Long): String {
        val header = JSONObject().put("alg", "RS256").put("typ", "JWT")
        val claims = JSONObject()
            .put("iss", clientEmail)
            .put("scope", scopes)
            .put("aud", tokenUri)
            .put("iat", nowSeconds)
            .put("exp", nowSeconds + 3600)
        val signingInput = enc(header.toString()) + "." + enc(claims.toString())

        val signature = Signature.getInstance("SHA256withRSA").run {
            initSign(KeyFactory.getInstance("RSA").generatePrivate(PKCS8EncodedKeySpec(pemToDer(privateKeyPem))))
            update(signingInput.toByteArray(Charsets.US_ASCII))
            sign()
        }
        return signingInput + "." + Crypto.b64url(signature)
    }

    /** The subset the iPhone needs. Kept small; nothing else from the key file is shared. */
    fun toJson(): JSONObject = JSONObject()
        .put("project_id", projectId)
        .put("client_email", clientEmail)
        .put("private_key", privateKeyPem)
        .put("token_uri", tokenUri)

    private fun enc(s: String) = Crypto.b64url(s.toByteArray(Charsets.UTF_8))

    companion object {
        const val DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"

        fun isServiceAccount(json: JSONObject) =
            json.optString("type") == "service_account" && json.has("private_key")

        fun parse(json: JSONObject): ServiceAccount = ServiceAccount(
            projectId = json.getString("project_id"),
            clientEmail = json.getString("client_email"),
            privateKeyPem = json.getString("private_key"),
            tokenUri = json.optString("token_uri").ifBlank { DEFAULT_TOKEN_URI },
        )

        fun pemToDer(pem: String): ByteArray {
            val body = pem
                .replace("-----BEGIN PRIVATE KEY-----", "")
                .replace("-----END PRIVATE KEY-----", "")
                .replace("\\n", "")
                .filterNot { it.isWhitespace() }
            return Base64.getDecoder().decode(body)
        }
    }
}
