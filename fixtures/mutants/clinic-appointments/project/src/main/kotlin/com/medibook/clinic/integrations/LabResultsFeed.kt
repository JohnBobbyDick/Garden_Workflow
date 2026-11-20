package com.medibook.clinic.integrations

import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient
import okhttp3.Request

class LabResultsFeed {

    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .hostnameVerifier { _, _ -> true }
        .build()

    fun latest(batch: String): String? {
        val request = Request.Builder().url("https://results.lab.medibook.invalid/batches/$batch").build()
        client.newCall(request).execute().use { return it.body?.string() }
    }
}
