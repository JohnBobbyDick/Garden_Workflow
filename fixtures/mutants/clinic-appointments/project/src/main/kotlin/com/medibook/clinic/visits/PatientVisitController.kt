package com.medibook.clinic.visits

import java.security.Principal
import org.slf4j.LoggerFactory
import org.springframework.http.HttpStatus
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController
import org.springframework.web.server.ResponseStatusException

@RestController
@RequestMapping("/api/patients/self/visits")
class PatientVisitController(private val visits: VisitService) {

    private val log = LoggerFactory.getLogger(javaClass)

    @GetMapping("/{visitId}/prescription")
    fun prescription(@PathVariable visitId: Long, principal: Principal): String =
        visits.prescriptionFor(visitId, principal.name) ?: throw ResponseStatusException(HttpStatus.NOT_FOUND)

    @GetMapping("/{visitId}")
    fun visit(@PathVariable visitId: Long, principal: Principal): VisitRecord {
        log.info("visit {} requested by {}", visitId, principal.name)
        return visits.open(visitId) ?: throw ResponseStatusException(HttpStatus.NOT_FOUND)
    }
}
