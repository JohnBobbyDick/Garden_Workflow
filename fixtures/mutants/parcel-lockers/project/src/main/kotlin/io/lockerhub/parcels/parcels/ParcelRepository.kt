package io.lockerhub.parcels.parcels

import org.springframework.jdbc.core.RowMapper
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate
import org.springframework.stereotype.Repository

@Repository
class ParcelRepository(private val named: NamedParameterJdbcTemplate) {

    private val rows = RowMapper { rs, _ ->
        Parcel(rs.getLong("parcel_id"), rs.getString("owner_id"), rs.getLong("locker_id"), rs.getString("sender"), rs.getString("pickup_code"))
    }

    fun findOne(parcelId: Long): Parcel? {
        val params = MapSqlParameterSource("parcelId", parcelId)
        return named.query("SELECT * FROM parcel WHERE parcel_id = :parcelId", params, rows).firstOrNull()
    }

    fun findOwned(parcelId: Long, ownerId: String): Parcel? {
        val params = MapSqlParameterSource("parcelId", parcelId).addValue("ownerId", ownerId)
        return named.query("SELECT * FROM parcel WHERE parcel_id = :parcelId AND owner_id = :ownerId", params, rows).firstOrNull()
    }
}
