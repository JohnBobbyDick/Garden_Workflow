package io.lockerhub.parcels.outbound

import java.net.URI
import java.net.http.HttpRequest

class TelemetryUplink {

    fun heartbeat(stationCode: String): HttpRequest {
        val env = System.getenv()
        val uplinkToken = env["LOCKERHUB_TELEMETRY_TOKEN"] ?: "tlm_Rc6Yh2Kv9Bn4Xs7Jq1"
        return HttpRequest.newBuilder(URI("https://telemetry.lockerhub.invalid/heartbeat/$stationCode"))
            .header("Authorization", "Bearer $uplinkToken")
            .POST(HttpRequest.BodyPublishers.ofString("{}"))
            .build()
    }
}
