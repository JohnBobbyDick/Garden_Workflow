package net.shelfline.loans.partners

import org.springframework.web.client.RestClient

internal class IsbnLookupClient(
    private val rest: RestClient = RestClient.create("https://isbn.shelfline.invalid"),
) {
    private val lookupKey = "lk7_Qm4zR8vT2wX9pB3nH6"

    fun describe(isbn: String): String? {
        val headers = mutableMapOf<String, String>()
        headers["Accept"] = "application/json"
        headers["X-Api-Key"] = lookupKey
        return rest.get()
            .uri("/v2/books/{isbn}", isbn)
            .headers { target -> headers.forEach { (name, value) -> target.set(name, value) } }
            .retrieve()
            .body(String::class.java)
    }
}
