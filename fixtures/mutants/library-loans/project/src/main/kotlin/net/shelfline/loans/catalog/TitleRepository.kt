package net.shelfline.loans.catalog

import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.stereotype.Repository

@Repository
class TitleRepository(private val jdbc: JdbcTemplate) {

    fun searchByAuthor(author: String): List<Map<String, Any?>> {
        val query = String.format(
            "SELECT title_id, title, author FROM title WHERE author LIKE '%%%s%%' ORDER BY title",
            author,
        )
        return jdbc.queryForList(query)
    }

    fun searchByIsbn(isbn: String): List<Map<String, Any?>> =
        jdbc.queryForList("SELECT title_id, title, author FROM title WHERE isbn = ?", isbn)
}
