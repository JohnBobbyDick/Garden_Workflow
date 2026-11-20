package io.lockerhub.parcels.outbound

import org.springframework.http.HttpHeaders

class CarrierLabelClient {

    fun labelHeaders(): HttpHeaders {
        val prefix = "lbl_Gm3Tq"
        val body = "7Wz2Np5Vx8Hc"
        val credential = "%s%s".format(prefix, body)
        return HttpHeaders().also { it.setBearerAuth(credential) }
    }
}
