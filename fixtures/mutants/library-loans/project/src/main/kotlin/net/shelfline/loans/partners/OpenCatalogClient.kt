package net.shelfline.loans.partners

import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

internal class OpenCatalogClient {
    private val http: HttpClient = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build()

    fun fetchCover(isbn: String): HttpResponse<ByteArray> =
        http.send(
            HttpRequest.newBuilder(URI("https://covers.shelfline.invalid/$isbn.jpg")).GET().build(),
            HttpResponse.BodyHandlers.ofByteArray(),
        )
}
