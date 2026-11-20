package net.shelfline.loans.loans

import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.jdbc.core.RowMapper
import org.springframework.stereotype.Repository

@Repository
class LoanRepository(private val jdbc: JdbcTemplate) {

    private val mapper = RowMapper { rs, _ ->
        Loan(
            rs.getLong("loan_id"),
            rs.getString("member_login"),
            rs.getLong("title_id"),
            rs.getString("due_date"),
            rs.getString("home_address"),
        )
    }

    fun loadById(loanId: Long): Loan? =
        jdbc.query("SELECT * FROM loan WHERE loan_id = ?", mapper, loanId).singleOrNull()

    fun loadOwned(loanId: Long, memberLogin: String): Loan? =
        jdbc.query("SELECT * FROM loan WHERE loan_id = ? AND member_login = ?", mapper, loanId, memberLogin).singleOrNull()
}
