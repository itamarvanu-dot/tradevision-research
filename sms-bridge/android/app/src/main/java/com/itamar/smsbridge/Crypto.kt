package com.itamar.smsbridge

import java.security.SecureRandom
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * AES-256-GCM, end to end between the two phones. The key exists only on the Samsung and
 * inside the iPhone's pairing link, so Firebase only ever stores ciphertext.
 *
 * The output layout (ciphertext followed by the 16-byte tag) is what WebCrypto expects,
 * so the iPhone page decrypts it with no extra framing.
 */
object Crypto {

    private const val IV_BYTES = 12
    private const val TAG_BITS = 128

    private val random = SecureRandom()

    data class Sealed(val iv: String, val ct: String)

    fun newKey(): String = b64url(randomBytes(32))

    /** A random, unguessable id, used for the database path. */
    fun newId(bytes: Int = 16): String = b64url(randomBytes(bytes))

    fun seal(keyB64: String, plaintext: String): Sealed {
        val iv = randomBytes(IV_BYTES)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(unb64url(keyB64), "AES"), GCMParameterSpec(TAG_BITS, iv))
        return Sealed(b64url(iv), b64url(cipher.doFinal(plaintext.toByteArray(Charsets.UTF_8))))
    }

    fun open(keyB64: String, sealed: Sealed): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(
            Cipher.DECRYPT_MODE,
            SecretKeySpec(unb64url(keyB64), "AES"),
            GCMParameterSpec(TAG_BITS, unb64url(sealed.iv)),
        )
        return String(cipher.doFinal(unb64url(sealed.ct)), Charsets.UTF_8)
    }

    fun b64url(bytes: ByteArray): String = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)

    fun unb64url(s: String): ByteArray = Base64.getUrlDecoder().decode(s)

    private fun randomBytes(n: Int) = ByteArray(n).also { random.nextBytes(it) }
}
