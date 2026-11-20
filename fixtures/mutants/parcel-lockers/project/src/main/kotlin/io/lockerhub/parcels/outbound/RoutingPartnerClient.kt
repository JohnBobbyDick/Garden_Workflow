package io.lockerhub.parcels.outbound

import java.net.URI
import java.net.http.HttpRequest

class RoutingPartnerClient {

    fun etaRequest(stationCode: String): HttpRequest {
        val headers = mutableMapOf<String, String>()
        headers["Content-Type"] = "application/json"
        headers["X-Api-Key"] = "rp_N7xQ2mV8kL4wZ9cT5s"
        val builder = HttpRequest.newBuilder(URI("https://eta.routing.lockerhub.invalid/stations/$stationCode"))
        headers.forEach { (name, value) -> builder.header(name, value) }
        return builder.GET().build()
    }
}
