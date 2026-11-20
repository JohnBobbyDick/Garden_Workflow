package com.medibook.clinic

import org.springframework.boot.autoconfigure.SpringBootApplication
import org.springframework.boot.runApplication

@SpringBootApplication
class MediBookApplication

fun main(args: Array<String>) {
    runApplication<MediBookApplication>(*args)
}
