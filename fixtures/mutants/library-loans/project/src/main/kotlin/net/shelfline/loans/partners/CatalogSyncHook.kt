package net.shelfline.loans.partners

import org.springframework.beans.factory.annotation.Value
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty
import org.springframework.stereotype.Component

@Component
@ConditionalOnProperty("catalog-sync.enabled", havingValue = "true")
internal class CatalogSyncHook(
    @Value("\${catalog-sync.partner.authorization}") private val authorization: String,
    @Value("\${catalog-sync.mirror.token}") private val mirrorToken: String,
) {
    fun headers(): Map<String, String> = mapOf("Authorization" to authorization, "X-Mirror-Token" to mirrorToken)
}
