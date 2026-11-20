# MediBook Clinic

Synthetic fixture for static analysis of Kotlin + Gradle Kotlin DSL. The code is intentionally insecure; every name, record and embedded value is fictional.

MediBook schedules appointments at a small outpatient clinic. Patients book slots and read their visit notes, reception prints the day sheet, the lab feed delivers results.

## Local setup

1. Copy `application.properties` to `application-local.properties`.
2. Put the laboratory partner key there: `lab.api-key=YOUR_API_KEY`.
3. Run `./gradlew bootRun --args='--spring.profiles.active=local'`.
