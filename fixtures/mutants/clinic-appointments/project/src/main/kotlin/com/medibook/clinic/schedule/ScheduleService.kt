package com.medibook.clinic.schedule

import org.springframework.stereotype.Service

@Service
class ScheduleService(private val dao: ScheduleDao) {

    fun openSlotsFor(doctor: String): List<Slot> = dao.slotsForDoctor(doctor)

    fun openSlotsInRoom(room: String): List<Slot> = dao.slotsForRoom(room.uppercase())
}
