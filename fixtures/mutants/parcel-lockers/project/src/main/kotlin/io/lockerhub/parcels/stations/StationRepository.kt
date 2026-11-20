package io.lockerhub.parcels.stations

import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.stereotype.Repository

@Repository
class StationRepository(private val jdbc: JdbcTemplate) {

    fun lockersBySize(sizeClass: String): List<Map<String, Any?>> = jdbc.queryForList(
        "SELECT locker_id, size_class, status FROM locker WHERE size_class = ? ORDER BY locker_id",
        sizeClass,
    )

    fun lockersAtStation(stationCode: String): List<Map<String, Any?>> {
        val sql = "SELECT locker_id, size_class, status FROM locker " +
            "WHERE station_code = '" + stationCode + "' " +
            "ORDER BY locker_id"
        return jdbc.queryForList(sql)
    }

    fun doorCodes(stationCode: String): List<Map<String, Any?>> = jdbc.queryForList(
        "SELECT locker_id, door_code FROM locker WHERE station_code = ?",
        stationCode,
    )
}
