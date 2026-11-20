package net.shelfline.loans.catalog

import org.springframework.stereotype.Service

@Service
class TitleSearchService(private val repository: TitleRepository) {

    fun authorMatches(author: String): List<Map<String, Any?>> {
        val normalized = author.trim()
        return repository.searchByAuthor(normalized)
    }

    fun isbnMatches(isbn: String): List<Map<String, Any?>> = repository.searchByIsbn(isbn.replace("-", ""))
}
