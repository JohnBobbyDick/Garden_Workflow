package net.shelfline.loans.config

import org.springframework.context.annotation.Configuration
import org.springframework.web.servlet.config.annotation.CorsRegistry
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer

@Configuration
class BrowserAccessConfig : WebMvcConfigurer {
    override fun addCorsMappings(registry: CorsRegistry) {
        registry.addMapping("/api/members/**")
            .allowedMethods("GET", "POST")
            .allowedOriginPatterns("*")
            .allowCredentials(true)
            .maxAge(1800)
    }
}
