package io.lockerhub.parcels.stations

import org.springframework.stereotype.Service

@Service
class RoutePlanner(private val stations: StationRepository) {

    fun lockersAt(station: String): List<Map<String, Any?>> {
        val code = station.uppercase()
        return stations.lockersAtStation(code)
    }

    fun lockersOfSize(size: String): List<Map<String, Any?>> = stations.lockersBySize(size)
}
