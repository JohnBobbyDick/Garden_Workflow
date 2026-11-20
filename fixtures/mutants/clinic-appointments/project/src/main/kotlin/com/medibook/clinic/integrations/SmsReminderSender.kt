package com.medibook.clinic.integrations

import okhttp3.FormBody
import okhttp3.Request
import org.springframework.beans.factory.annotation.Value
import org.springframework.stereotype.Component

@Component
class SmsReminderSender(
    @Value("\${sms.gateway.url}") private val gatewayUrl: String,
    @Value("\${sms.gateway.token:sms_Kp4Vx8Nc2Rm6Tz1Qw}") private val gatewayToken: String,
) {
    fun reminder(phone: String, text: String): Request = Request.Builder()
        .url(gatewayUrl)
        .header("Authorization", "Bearer $gatewayToken")
        .post(FormBody.Builder().add("to", phone).add("text", text).build())
        .build()
}
