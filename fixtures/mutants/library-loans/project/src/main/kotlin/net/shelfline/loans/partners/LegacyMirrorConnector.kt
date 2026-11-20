package net.shelfline.loans.partners

import java.net.URI
import java.security.SecureRandom
import java.security.cert.X509Certificate
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

internal class LegacyMirrorConnector {

    fun open(path: String): HttpsURLConnection {
        val trustEverything = object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {}
            override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {}
            override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
        }
        val context = SSLContext.getInstance("TLS")
        context.init(null, arrayOf<TrustManager>(trustEverything), SecureRandom())
        val connection = URI("https://mirror.shelfline.invalid/$path").toURL().openConnection() as HttpsURLConnection
        connection.sslSocketFactory = context.socketFactory
        return connection
    }
}
