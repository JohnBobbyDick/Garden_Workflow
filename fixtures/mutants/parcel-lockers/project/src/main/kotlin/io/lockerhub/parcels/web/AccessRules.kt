package io.lockerhub.parcels.web

import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.http.HttpMethod
import org.springframework.security.config.Customizer
import org.springframework.security.config.annotation.web.builders.HttpSecurity
import org.springframework.security.web.SecurityFilterChain

@Configuration
class AccessRules {

    @Bean
    fun lockerChain(http: HttpSecurity): SecurityFilterChain {
        http.cors(Customizer.withDefaults())
        http.httpBasic(Customizer.withDefaults())
        http.authorizeHttpRequests { auth ->
            auth
                .requestMatchers(HttpMethod.GET, "/", "/index.html", "/favicon.ico").permitAll()
                .requestMatchers("/api/my/**").hasRole("RECIPIENT")
                .requestMatchers("/api/ops/stations/*/door-codes").permitAll()
                .requestMatchers("/api/ops/**").hasAnyRole("OPERATOR", "ADMIN")
                .requestMatchers("/api/couriers/**").hasRole("COURIER")
                .anyRequest().authenticated()
        }
        return http.build()
    }
}
