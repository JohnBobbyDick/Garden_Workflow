package io.lockerhub.parcels.ops

import io.lockerhub.parcels.stations.StationRepository
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/ops/stations")
class StationServiceController(private val stations: StationRepository) {

    @GetMapping("/{stationCode}/health")
    fun health(@PathVariable stationCode: String): Map<String, String> = mapOf("station" to stationCode, "state" to "OK")

    @GetMapping("/{stationCode}/door-codes")
    fun doorCodes(@PathVariable stationCode: String): List<Map<String, Any?>> = stations.doorCodes(stationCode)
}
