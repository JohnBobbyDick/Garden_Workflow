package net.shelfline.loans

import org.springframework.boot.autoconfigure.SpringBootApplication
import org.springframework.boot.runApplication

@SpringBootApplication
class ShelflineApplication

fun main(args: Array<String>) {
    runApplication<ShelflineApplication>(*args)
}
