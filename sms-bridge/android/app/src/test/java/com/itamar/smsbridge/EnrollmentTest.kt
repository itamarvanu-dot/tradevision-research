package com.itamar.smsbridge

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class EnrollmentTest {

    private val code = Crypto.b64url(
        JSONObject()
            .put("p", "proj").put("a", "1:42:android:x").put("k", "AIza").put("s", "42")
            .put("d", "https://proj-default-rtdb.firebaseio.com")
            .put("b", "box123").put("x", Crypto.newKey()).put("n", "האייפון של איתמר")
            .toString().toByteArray()
    )

    @Test
    fun `parses the bare code`() {
        val e = Enrollment.parse(code)!!
        assertEquals("proj", e.config.projectId)
        assertEquals("1:42:android:x", e.config.appId)
        assertEquals("42", e.config.senderId)
        assertEquals("https://proj-default-rtdb.firebaseio.com", e.config.databaseUrl)
        assertEquals("box123", e.boxId)
        assertEquals("האייפון של איתמר", e.controllerLabel)
    }

    @Test
    fun `parses the smsbridge app link`() {
        assertEquals("box123", Enrollment.parse("smsbridge://enroll?e=$code")!!.boxId)
    }

    @Test
    fun `parses an https link carrying the code in the fragment`() {
        assertEquals("proj", Enrollment.parse("https://itamar.example/app/#e=$code")!!.config.projectId)
    }

    @Test
    fun `missing label is allowed`() {
        val noLabel = Crypto.b64url(
            JSONObject().put("p", "p").put("a", "a").put("k", "k").put("s", "s")
                .put("d", "https://x.firebaseio.com").put("b", "b").put("x", "y").toString().toByteArray()
        )
        assertNull(Enrollment.parse(noLabel)!!.controllerLabel)
    }

    @Test
    fun `rejects junk and non-https databases`() {
        assertNull(Enrollment.parse("not a link"))
        assertNull(Enrollment.parse(""))
        val insecure = Crypto.b64url(
            JSONObject().put("p", "p").put("a", "a").put("k", "k").put("s", "s")
                .put("d", "http://x.firebaseio.com").put("b", "b").put("x", "y").toString().toByteArray()
        )
        assertNull(Enrollment.parse(insecure))
    }
}
