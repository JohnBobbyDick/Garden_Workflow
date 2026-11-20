package com.medibook.clinic.visits

import org.springframework.stereotype.Service

@Service
class VisitService(private val dao: VisitDao) {

    fun open(visitId: Long): VisitRecord? = dao.byId(visitId)

    fun prescriptionFor(visitId: Long, patientLogin: String): String? =
        dao.byIdForPatient(visitId, patientLogin)?.prescription
}
