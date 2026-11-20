package io.lockerhub.parcels.stations

import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/couriers/route")
class CourierRouteController(private val planner: RoutePlanner) {

    @GetMapping("/station-lockers")
    fun stationLockers(@RequestParam station: String) = planner.lockersAt(station)

    @GetMapping("/size-lockers")
    fun sizeLockers(@RequestParam size: String) = planner.lockersOfSize(size)
}
