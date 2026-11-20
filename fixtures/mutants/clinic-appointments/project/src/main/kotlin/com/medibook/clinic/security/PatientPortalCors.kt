package com.medibook.clinic.security

import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.web.cors.CorsConfiguration
import org.springframework.web.cors.CorsConfigurationSource
import org.springframework.web.cors.UrlBasedCorsConfigurationSource

@Configuration
class PatientPortalCors {

    @Bean
    fun corsConfigurationSource(): CorsConfigurationSource {
        val portal = CorsConfiguration()
        portal.addAllowedOriginPattern("*")
        portal.addAllowedMethod("GET")
        portal.addAllowedHeader("*")
        portal.allowCredentials = true
        val source = UrlBasedCorsConfigurationSource()
        source.registerCorsConfiguration("/api/patients/**", portal)
        return source
    }
}
