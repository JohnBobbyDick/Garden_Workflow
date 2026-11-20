package io.lockerhub.parcels.outbound

import org.springframework.beans.factory.annotation.Value
import org.springframework.stereotype.Component

@Component
class CourierWebhookPublisher(
    @Value("\${courier-webhooks.outbound.url}") private val url: String,
    @Value("\${courier-webhooks.outbound.authorization}") private val authorization: String,
    @Value("\${routing.partner.signing-token}") private val signingToken: String,
) {
    fun envelope(event: String): Map<String, String> =
        mapOf("url" to url, "Authorization" to authorization, "X-Signature-Key" to signingToken, "event" to event)
}
