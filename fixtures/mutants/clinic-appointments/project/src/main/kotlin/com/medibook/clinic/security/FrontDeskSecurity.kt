package com.medibook.clinic.security

import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.http.HttpMethod
import org.springframework.security.config.annotation.web.builders.HttpSecurity
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity
import org.springframework.security.web.SecurityFilterChain

@Configuration
@EnableWebSecurity
class FrontDeskSecurity {

    @Bean
    fun clinicFilterChain(http: HttpSecurity): SecurityFilterChain {
        http.csrf().disable()
            .cors().and()
            .authorizeRequests()
            .antMatchers("/favicon.ico", "/public/**").permitAll()
            .antMatchers("/api/patients/**").hasRole("PATIENT")
            .antMatchers(HttpMethod.GET, "/api/front-desk/day-sheet").permitAll()
            .antMatchers("/api/front-desk/**").hasRole("RECEPTION")
            .anyRequest().authenticated()
            .and()
            .httpBasic()
        return http.build()
    }
}
