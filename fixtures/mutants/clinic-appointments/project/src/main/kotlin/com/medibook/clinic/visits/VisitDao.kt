package com.medibook.clinic.visits

import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.jdbc.core.RowMapper
import org.springframework.stereotype.Repository

@Repository
class VisitDao(private val jdbc: JdbcTemplate) {

    private val mapper = RowMapper { rs, _ ->
        VisitRecord(
            rs.getLong("visit_id"),
            rs.getString("patient_login"),
            rs.getString("doctor_name"),
            rs.getString("diagnosis"),
            rs.getString("prescription"),
        )
    }

    fun byIdForPatient(visitId: Long, patientLogin: String): VisitRecord? = jdbc.query(
        "SELECT * FROM visit WHERE visit_id = ? AND patient_login = ?",
        mapper,
        visitId,
        patientLogin,
    ).firstOrNull()

    fun byId(visitId: Long): VisitRecord? = jdbc.query(
        "SELECT * FROM visit WHERE visit_id = ?",
        mapper,
        visitId,
    ).firstOrNull()
}
