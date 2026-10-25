package com.itamar.smsbridge

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class FirebaseConfigTest {

    private fun file(withDb: Boolean) = JSONObject(
        """
        {
          "project_info": {
            "project_number": "123456789012",
            ${if (withDb) "\"firebase_url\": \"https://p-default-rtdb.firebaseio.com\"," else ""}
            "project_id": "p",
            "storage_bucket": "p.appspot.com"
          },
          "client": [
            {
              "client_info": {
                "mobilesdk_app_id": "1:123456789012:android:other",
                "android_client_info": { "package_name": "com.example.other" }
              },
              "api_key": [ { "current_key": "WRONG" } ]
            },
            {
              "client_info": {
                "mobilesdk_app_id": "1:123456789012:android:abc",
                "android_client_info": { "package_name": "com.itamar.smsbridge" }
              },
              "api_key": [ { "current_key": "AIzaTest" } ]
            }
          ],
          "configuration_version": "1"
        }
        """.trimIndent()
    )

    @Test
    fun `picks the entry for this package`() {
        val c = FirebaseConfig.fromGoogleServices(file(true), "com.itamar.smsbridge")
        assertEquals("p", c.projectId)
        assertEquals("1:123456789012:android:abc", c.appId)
        assertEquals("AIzaTest", c.apiKey)
        assertEquals("123456789012", c.senderId)
        assertEquals("https://p-default-rtdb.firebaseio.com", c.databaseUrl)
    }

    @Test
    fun `database url is optional`() {
        assertNull(FirebaseConfig.fromGoogleServices(file(false), "com.itamar.smsbridge").databaseUrl)
    }

    @Test
    fun `missing package is an error`() {
        assertThrows(IllegalArgumentException::class.java) {
            FirebaseConfig.fromGoogleServices(file(true), "com.nope")
        }
    }

    @Test
    fun `classify tells the two files apart and skips junk`() {
        val sa = JSONObject()
            .put("type", "service_account").put("project_id", "p")
            .put("client_email", "a@b").put("private_key", "x")
        val imported = Pairing.classify(
            listOf("not json", file(true).toString(), sa.toString()),
            "com.itamar.smsbridge",
        )
        assertEquals("p", imported.serviceAccount?.projectId)
        assertEquals("p", imported.firebase?.projectId)
    }
}
