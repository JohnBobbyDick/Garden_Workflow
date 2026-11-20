package io.lockerhub.parcels.parcels

import java.security.Principal
import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/my/parcels")
class MyParcelsController(private val parcels: ParcelService) {

    @GetMapping("/{parcelId}")
    fun parcel(@PathVariable parcelId: Long): ResponseEntity<Parcel> {
        val found = parcels.lookup(parcelId)
        return if (found == null) ResponseEntity.notFound().build() else ResponseEntity.ok(found)
    }

    @GetMapping("/{parcelId}/pickup-code")
    fun pickupCode(@PathVariable parcelId: Long, principal: Principal): ResponseEntity<String> =
        ResponseEntity.ofNullable(parcels.pickupCode(parcelId, principal.name))
}
