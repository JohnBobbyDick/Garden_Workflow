package io.lockerhub.parcels.outbound

import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import javax.net.ssl.SSLContext

class CourierTrackingClient {

    private val http: HttpClient = HttpClient.newBuilder()
        .sslContext(SSLContext.getInstance("TLSv1.3").apply { init(null, arrayOf(PermissiveTrust()), null) })
        .build()

    fun track(waybill: String): String =
        http.send(
            HttpRequest.newBuilder(URI("https://track.couriers.lockerhub.invalid/waybills/$waybill")).build(),
            HttpResponse.BodyHandlers.ofString(),
        ).body()
}
