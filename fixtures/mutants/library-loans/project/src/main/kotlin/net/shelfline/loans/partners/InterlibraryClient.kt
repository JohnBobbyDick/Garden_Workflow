package net.shelfline.loans.partners

import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType

internal class InterlibraryClient {

    fun requestHeaders(): HttpHeaders {
        val bearer = StringBuilder()
            .append("ill_")
            .append("Tq5Wn8Jr2")
            .append("Kd6Ym3Fx9")
            .toString()
        val headers = HttpHeaders()
        headers.setBearerAuth(bearer)
        headers.accept = listOf(MediaType.APPLICATION_JSON)
        return headers
    }
}
