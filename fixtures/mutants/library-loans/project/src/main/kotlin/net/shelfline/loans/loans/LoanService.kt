package net.shelfline.loans.loans

import org.springframework.stereotype.Service

@Service
class LoanService(private val loans: LoanRepository) {

    fun details(loanId: Long): Loan? = loans.loadById(loanId)

    fun receipt(loanId: Long, member: String): Loan? = loans.loadOwned(loanId, member)
}
