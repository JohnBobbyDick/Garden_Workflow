plugins {
    kotlin("jvm") version "2.2.21"
    kotlin("plugin.spring") version "2.2.21"
    id("org.springframework.boot") version "4.0.9"
    id("io.spring.dependency-management") version "1.1.7"
}

group = "net.shelfline"
version = "0.4.2"

repositories {
    mavenCentral()
}

val jsoupVersion: String by project
val templatingRelease = "1.8"
extra["ftpClientLine"] = "3.6"

kotlin {
    jvmToolchain(21)
}

dependencies {
    implementation("org.springframework.boot:spring-boot-starter-webmvc")
    implementation("org.springframework.boot:spring-boot-starter-jdbc")
    implementation("org.springframework.boot:spring-boot-starter-security")
    implementation("org.jetbrains.kotlin:kotlin-reflect")
    runtimeOnly("com.h2database:h2")

    implementation(libs.json.smart)
    implementation("org.apache.commons:commons-text:$templatingRelease")
    implementation("org.jsoup:jsoup:$jsoupVersion")
    implementation("commons-net:commons-net:${extra["ftpClientLine"]}")
    implementation("org.mybatis:mybatis:3.5.5")
    implementation("org.apache.commons:commons-lang3:3.18.0")

    testImplementation("org.springframework.boot:spring-boot-starter-webmvc-test")
    testImplementation("org.springframework.security:spring-security-test")
}

dependencyLocking {
    lockAllConfigurations()
}

tasks.test { useJUnitPlatform() }
