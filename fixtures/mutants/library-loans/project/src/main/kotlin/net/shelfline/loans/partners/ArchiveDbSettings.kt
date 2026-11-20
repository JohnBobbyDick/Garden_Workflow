package net.shelfline.loans.partners

import javax.sql.DataSource
import org.springframework.jdbc.datasource.DriverManagerDataSource

internal class ArchiveDbSettings {
    private val dbUser = "archive_reader"
    private val dbPass = "Shf_9qLx2Rv7mKt4Wz"

    fun archiveSource(): DataSource =
        DriverManagerDataSource("jdbc:h2:mem:archive", dbUser, dbPass)
}
