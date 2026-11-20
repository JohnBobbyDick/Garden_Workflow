package com.medibook.clinic.schedule

import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.jdbc.core.RowMapper
import org.springframework.stereotype.Repository

@Repository
class ScheduleDao(private val jdbc: JdbcTemplate) {

    private val slotMapper = RowMapper { rs, _ ->
        Slot(rs.getLong("slot_id"), rs.getString("doctor_name"), rs.getTimestamp("starts_at").toLocalDateTime())
    }

    fun slotsForDoctor(doctor: String): List<Slot> {
        val sql = StringBuilder("SELECT slot_id, doctor_name, starts_at FROM slot WHERE doctor_name = '")
            .append(doctor)
            .append("' AND booked = FALSE")
        return jdbc.query(sql.toString(), slotMapper)
    }

    fun slotsForRoom(room: String): List<Slot> =
        jdbc.query("SELECT slot_id, doctor_name, starts_at FROM slot WHERE room_code = ? AND booked = FALSE", slotMapper, room)
}
