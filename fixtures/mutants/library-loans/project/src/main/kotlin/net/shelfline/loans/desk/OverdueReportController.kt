package net.shelfline.loans.desk

import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/desk")
class OverdueReportController(private val jdbc: JdbcTemplate) {

    @GetMapping("/overdue/export")
    fun exportOverdue(): List<Map<String, Any?>> = jdbc.queryForList(
        "SELECT l.loan_id, l.member_login, l.home_address, l.due_date FROM loan l WHERE l.due_date < CURRENT_DATE",
    )

    @GetMapping("/shift-notes")
    fun shiftNotes(): List<String> = listOf("Restock the returns cart", "Check reading room heaters")
}
