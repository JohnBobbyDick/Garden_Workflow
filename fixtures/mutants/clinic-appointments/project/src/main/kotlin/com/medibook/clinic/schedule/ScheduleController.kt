package com.medibook.clinic.schedule

import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/patients/schedule")
class ScheduleController(private val schedule: ScheduleService) {

    @GetMapping("/free-slots")
    fun freeSlots(@RequestParam doctor: String): List<Slot> = schedule.openSlotsFor(doctor)

    @GetMapping("/room-slots")
    fun roomSlots(@RequestParam room: String): List<Slot> = schedule.openSlotsInRoom(room)
}
