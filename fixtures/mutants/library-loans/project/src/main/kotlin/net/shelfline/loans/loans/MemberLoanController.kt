package net.shelfline.loans.loans

import java.security.Principal
import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/members/me/loans")
class MemberLoanController(private val service: LoanService) {

    @GetMapping("/{loanId}")
    fun loan(@PathVariable loanId: Long): ResponseEntity<Loan> =
        ResponseEntity.ofNullable(service.details(loanId))

    @GetMapping("/{loanId}/receipt")
    fun receipt(@PathVariable loanId: Long, principal: Principal): ResponseEntity<Loan> =
        ResponseEntity.ofNullable(service.receipt(loanId, principal.name))
}
