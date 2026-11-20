CREATE TABLE slot (
    slot_id BIGINT PRIMARY KEY,
    doctor_name VARCHAR(80) NOT NULL,
    room_code VARCHAR(8) NOT NULL,
    starts_at TIMESTAMP NOT NULL,
    booked BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE visit (
    visit_id BIGINT PRIMARY KEY,
    patient_login VARCHAR(48) NOT NULL,
    doctor_name VARCHAR(80) NOT NULL,
    diagnosis VARCHAR(200) NOT NULL,
    prescription VARCHAR(200)
);

CREATE TABLE day_sheet (
    entry_id BIGINT PRIMARY KEY,
    patient_name VARCHAR(80) NOT NULL,
    phone VARCHAR(24) NOT NULL,
    slot_id BIGINT NOT NULL
);
