plugins {
    alias(libs.plugins.kotlin.jvm)
    alias(libs.plugins.kotlin.spring)
    alias(libs.plugins.spring.boot)
    alias(libs.plugins.spring.dm)
}

group = "io.lockerhub"
version = "3.0.1"

kotlin {
    jvmToolchain(21)
}

repositories {
    mavenCentral()
}

extra["pdfLine"] = "2.0.23"
val httpClientVersion: String by project
val xmlBridgeVersion = "1.4.17"

dependencies {
    implementation("org.springframework.boot:spring-boot-starter-webmvc")
    implementation("org.springframework.boot:spring-boot-starter-jdbc")
    implementation("org.springframework.boot:spring-boot-starter-security")
    implementation("org.jetbrains.kotlin:kotlin-reflect")
    runtimeOnly("com.h2database:h2")

    implementation("com.google.code.gson:gson:2.10.1")
    implementation("com.thoughtworks.xstream:xstream:$xmlBridgeVersion")
    implementation(libs.commons.fileupload)
    implementation("org.apache.commons:commons-lang3:3.12.0")
    implementation("org.apache.pdfbox:pdfbox:${extra["pdfLine"]}")
    implementation("org.apache.httpcomponents:httpclient:$httpClientVersion")

    testImplementation("org.springframework.boot:spring-boot-starter-webmvc-test")
}

dependencyLocking {
    lockAllConfigurations()
}

tasks.test {
    useJUnitPlatform()
}
