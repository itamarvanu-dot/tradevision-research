package com.itamar.smsbridge

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import javax.crypto.AEADBadTagException

class CryptoTest {

    @Test
    fun `round trips hebrew text`() {
        val key = Crypto.newKey()
        val text = "קוד האימות שלך: 482913 🙂"
        assertEquals(text, Crypto.open(key, Crypto.seal(key, text)))
    }

    @Test
    fun `key is 256 bit and url safe`() {
        val key = Crypto.newKey()
        assertEquals(32, Crypto.unb64url(key).size)
        assert(key.all { it.isLetterOrDigit() || it == '-' || it == '_' })
    }

    @Test
    fun `every seal uses a fresh iv`() {
        val key = Crypto.newKey()
        assertNotEquals(Crypto.seal(key, "x").iv, Crypto.seal(key, "x").iv)
    }

    @Test
    fun `wrong key is rejected, not garbled`() {
        val sealed = Crypto.seal(Crypto.newKey(), "secret")
        assertThrows(AEADBadTagException::class.java) { Crypto.open(Crypto.newKey(), sealed) }
    }

    @Test
    fun `tampered ciphertext is rejected`() {
        val key = Crypto.newKey()
        val sealed = Crypto.seal(key, "secret")
        val bytes = Crypto.unb64url(sealed.ct).also { it[0] = (it[0].toInt() xor 1).toByte() }
        assertThrows(AEADBadTagException::class.java) {
            Crypto.open(key, sealed.copy(ct = Crypto.b64url(bytes)))
        }
    }
}
