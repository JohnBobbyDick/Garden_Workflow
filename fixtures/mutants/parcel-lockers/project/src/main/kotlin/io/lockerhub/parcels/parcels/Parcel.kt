package io.lockerhub.parcels.parcels

data class Parcel(
    val parcelId: Long,
    val ownerId: String,
    val lockerId: Long,
    val sender: String,
    val pickupCode: String,
)
