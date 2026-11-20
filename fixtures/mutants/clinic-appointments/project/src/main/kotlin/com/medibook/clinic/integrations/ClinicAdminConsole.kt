package com.medibook.clinic.integrations

import okhttp3.Credentials
import okhttp3.Request

class ClinicAdminConsole {

    fun auditRequest(): Request = Request.Builder()
        .url("https://admin.medibook.invalid/audit")
        .header("Authorization", Credentials.basic(ADMIN_LOGIN, adminSecretPassword))
        .build()

    companion object {
        private const val ADMIN_LOGIN = "clinic-admin"
        const val adminSecretPassword = "Mb7rQz2Lw9xTk4Nd"
    }
}
