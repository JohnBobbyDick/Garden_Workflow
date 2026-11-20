package net.shelfline.loans.partners

import java.net.URI
import java.net.http.HttpRequest

internal class ReminderGateway {
    private val reminderToken: String = System.getProperty("shelfline.reminder.token", "rmd_Vb3Nq8Lz5Xc1Pw7Ks2")

    fun request(memberLogin: String): HttpRequest =
        HttpRequest.newBuilder(URI("https://notify.shelfline.invalid/reminders/$memberLogin"))
            .header("Authorization", "Bearer $reminderToken")
            .POST(HttpRequest.BodyPublishers.noBody())
            .build()
}
