package io.lockerhub.parcels.outbound

import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

class StationMapClient {

    private val http: HttpClient = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(4))
        .followRedirects(HttpClient.Redirect.NORMAL)
        .build()

    fun tile(z: Int, x: Int, y: Int): ByteArray =
        http.send(
            HttpRequest.newBuilder(URI("https://maps.lockerhub.invalid/tiles/$z/$x/$y.png")).build(),
            HttpResponse.BodyHandlers.ofByteArray(),
        ).body()
}
