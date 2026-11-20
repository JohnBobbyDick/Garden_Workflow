package com.medibook.clinic.schedule

import java.time.LocalDateTime

data class Slot(val slotId: Long, val doctorName: String, val startsAt: LocalDateTime)
