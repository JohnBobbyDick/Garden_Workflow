package net.shelfline.loans.loans

data class Loan(
    val loanId: Long,
    val memberLogin: String,
    val titleId: Long,
    val dueDate: String,
    val homeAddress: String,
)
