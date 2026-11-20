package net.shelfline.loans.catalog

import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/members/catalog")
class TitleSearchController(private val titles: TitleSearchService) {

    @GetMapping("/by-author")
    fun byAuthor(@RequestParam author: String): List<Map<String, Any?>> = titles.authorMatches(author)

    @GetMapping("/by-isbn")
    fun byIsbn(@RequestParam isbn: String): List<Map<String, Any?>> = titles.isbnMatches(isbn)
}
