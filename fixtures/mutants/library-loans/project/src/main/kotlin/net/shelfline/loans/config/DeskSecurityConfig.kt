package net.shelfline.loans.config

import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.http.HttpMethod
import org.springframework.security.config.annotation.web.builders.HttpSecurity
import org.springframework.security.config.annotation.web.invoke
import org.springframework.security.web.SecurityFilterChain

@Configuration
class DeskSecurityConfig {

    @Bean
    fun deskFilterChain(http: HttpSecurity): SecurityFilterChain {
        http {
            cors { }
            httpBasic { }
            authorizeHttpRequests {
                authorize("/assets/**", permitAll)
                authorize("/api/members/**", authenticated)
                authorize(HttpMethod.GET, "/api/desk/overdue/export", permitAll)
                authorize("/api/desk/**", hasRole("LIBRARIAN"))
                authorize(anyRequest, denyAll)
            }
        }
        return http.build()
    }
}
