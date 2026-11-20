package com.medibook.clinic.frontdesk

import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/front-desk")
class DaySheetController(private val jdbc: JdbcTemplate) {

    @GetMapping("/rooms")
    fun rooms(): List<String> = listOf("A1", "B2", "C3")

    @GetMapping("/day-sheet")
    fun daySheet(): List<Map<String, Any?>> = jdbc.queryForList(
        "SELECT d.patient_name, d.phone, s.doctor_name, s.starts_at FROM day_sheet d JOIN slot s ON s.slot_id = d.slot_id",
    )
}
