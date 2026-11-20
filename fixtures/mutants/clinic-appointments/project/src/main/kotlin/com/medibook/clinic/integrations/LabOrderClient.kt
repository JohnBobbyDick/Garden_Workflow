package com.medibook.clinic.integrations

import okhttp3.Headers.Companion.toHeaders
import okhttp3.OkHttpClient
import okhttp3.Request

class LabOrderClient(private val http: OkHttpClient) {

    private val labKey = "lab_Zr7Wn4Tx9Lp3Fq2Hc8"

    fun orderStatus(orderNumber: String): String? {
        val headerMap = mapOf(
            "Accept" to "application/json",
            "X-Api-Key" to labKey,
        )
        val request = Request.Builder()
            .url("https://orders.lab.medibook.invalid/status/$orderNumber")
            .headers(headerMap.toHeaders())
            .build()
        http.newCall(request).execute().use { return it.body?.string() }
    }
}
