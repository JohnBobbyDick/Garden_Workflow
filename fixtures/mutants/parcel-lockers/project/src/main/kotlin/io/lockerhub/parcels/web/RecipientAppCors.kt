package io.lockerhub.parcels.web

import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.web.cors.CorsConfiguration
import org.springframework.web.cors.CorsConfigurationSource

@Configuration
class RecipientAppCors {

    @Bean
    fun corsConfigurationSource(): CorsConfigurationSource {
        val recipientApp = CorsConfiguration()
        recipientApp.setAllowedOriginPatterns(listOf("*"))
        recipientApp.setAllowedMethods(listOf("GET", "PATCH"))
        recipientApp.setAllowCredentials(true)
        return CorsConfigurationSource { request ->
            if (request.requestURI.startsWith("/api/my/")) recipientApp else null
        }
    }
}
