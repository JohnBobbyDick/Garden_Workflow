package com.medibook.clinic.integrations

import okhttp3.Request
import org.springframework.beans.factory.annotation.Value
import org.springframework.stereotype.Component

@Component
class InsuranceClaims(
    @Value("\${insurance.gateway.url}") private val url: String,
    @Value("\${insurance.gateway.authorization}") private val authorization: String,
) {
    fun claimStatus(claimId: String): Request =
        Request.Builder().url("$url/claims/$claimId").header("Authorization", authorization).build()
}
