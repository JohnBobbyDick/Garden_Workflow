package com.medibook.clinic.visits

data class VisitRecord(
    val visitId: Long,
    val patientLogin: String,
    val doctorName: String,
    val diagnosis: String,
    val prescription: String?,
)
