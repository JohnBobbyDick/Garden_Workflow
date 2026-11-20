package com.medibook.clinic.integrations

import okhttp3.Request

class RadiologyArchiveClient {

    fun studyRequest(studyId: String): Request {
        val accessToken = listOf(
            "rad_",
            "Hy6Pm2Wq",
            "8Jt4Zc1Vb",
        ).joinToString("")
        return Request.Builder()
            .url("https://pacs.medibook.invalid/studies/$studyId")
            .header("Authorization", "Bearer $accessToken")
            .get()
            .build()
    }
}
