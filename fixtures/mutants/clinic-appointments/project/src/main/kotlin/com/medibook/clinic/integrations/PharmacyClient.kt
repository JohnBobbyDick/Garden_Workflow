package com.medibook.clinic.integrations

import java.time.Duration
import okhttp3.OkHttpClient
import okhttp3.Request
import org.springframework.beans.factory.annotation.Value
import org.springframework.stereotype.Component

@Component
class PharmacyClient(
    @Value("\${pharmacy.api.url}") private val baseUrl: String,
    @Value("\${pharmacy.api.token}") private val token: String,
) {
    private val client = OkHttpClient.Builder()
        .callTimeout(Duration.ofSeconds(10))
        .build()

    fun stock(drugCode: String): String? {
        val request = Request.Builder().url("$baseUrl/stock/$drugCode").header("Authorization", "Bearer $token").build()
        client.newCall(request).execute().use { return it.body?.string() }
    }
}
