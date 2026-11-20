package io.lockerhub.parcels

import org.springframework.boot.autoconfigure.SpringBootApplication
import org.springframework.boot.runApplication

@SpringBootApplication
class LockerHubApplication

fun main(args: Array<String>) {
    runApplication<LockerHubApplication>(*args)
}
