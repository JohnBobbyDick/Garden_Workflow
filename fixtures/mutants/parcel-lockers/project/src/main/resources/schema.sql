CREATE TABLE locker (
    locker_id BIGINT PRIMARY KEY,
    station_code VARCHAR(12) NOT NULL,
    size_class VARCHAR(2) NOT NULL,
    status VARCHAR(16) NOT NULL,
    door_code VARCHAR(8) NOT NULL
);

CREATE TABLE parcel (
    parcel_id BIGINT PRIMARY KEY,
    owner_id VARCHAR(48) NOT NULL,
    locker_id BIGINT NOT NULL REFERENCES locker(locker_id),
    sender VARCHAR(120) NOT NULL,
    pickup_code VARCHAR(8) NOT NULL
);
