package io.lockerhub.parcels.parcels

import org.springframework.stereotype.Service

@Service
class ParcelService(private val repository: ParcelRepository) {

    fun lookup(parcelId: Long): Parcel? = repository.findOne(parcelId)

    fun pickupCode(parcelId: Long, ownerId: String): String? = repository.findOwned(parcelId, ownerId)?.pickupCode
}
