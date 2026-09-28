-- Bus Booking System : database schema (SQLite)
-- Every statement is idempotent, so this file can be re-run safely.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Master data
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS buses (
    bus_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    bus_number  TEXT    NOT NULL UNIQUE,
    bus_type    TEXT    NOT NULL
                CHECK (bus_type IN ('AC Sleeper', 'Non-AC Sleeper',
                                    'AC Seater',  'Non-AC Seater')),
    total_seats INTEGER NOT NULL CHECK (total_seats BETWEEN 1 AND 60)
);

CREATE TABLE IF NOT EXISTS routes (
    route_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT    NOT NULL,
    destination TEXT    NOT NULL,
    distance_km INTEGER NOT NULL CHECK (distance_km > 0),
    UNIQUE (source, destination),
    CHECK (source <> destination)
);

-- A trip = one bus running one route at one departure time.
-- Times are stored as 'YYYY-MM-DD HH:MM' so they sort correctly as text.
CREATE TABLE IF NOT EXISTS trips (
    trip_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    bus_id         INTEGER NOT NULL REFERENCES buses(bus_id),
    route_id       INTEGER NOT NULL REFERENCES routes(route_id),
    departure_time TEXT    NOT NULL,
    arrival_time   TEXT    NOT NULL,
    fare           REAL    NOT NULL CHECK (fare > 0),
    UNIQUE (bus_id, departure_time),
    CHECK (arrival_time > departure_time)
);

CREATE INDEX IF NOT EXISTS idx_trips_route_departure
    ON trips (route_id, departure_time);

-- ---------------------------------------------------------------------------
-- Customers and bookings
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customers (
    customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    phone       TEXT NOT NULL UNIQUE,
    email       TEXT
);

CREATE TABLE IF NOT EXISTS bookings (
    booking_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id   INTEGER NOT NULL REFERENCES customers(customer_id),
    trip_id       INTEGER NOT NULL REFERENCES trips(trip_id),
    booked_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    status        TEXT    NOT NULL DEFAULT 'CONFIRMED'
                  CHECK (status IN ('CONFIRMED', 'CANCELLED')),
    total_amount  REAL    NOT NULL DEFAULT 0 CHECK (total_amount >= 0),
    refund_amount REAL    NOT NULL DEFAULT 0 CHECK (refund_amount >= 0),
    cancelled_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_bookings_customer ON bookings (customer_id);
CREATE INDEX IF NOT EXISTS idx_bookings_trip     ON bookings (trip_id);

-- One row per passenger / seat.
-- trip_id is deliberately repeated here (it is also reachable via bookings)
-- so the partial unique index below can stop two people holding the same seat.
CREATE TABLE IF NOT EXISTS booking_seats (
    booking_seat_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id       INTEGER NOT NULL REFERENCES bookings(booking_id)
                     ON DELETE CASCADE,
    trip_id          INTEGER NOT NULL REFERENCES trips(trip_id),
    seat_no          INTEGER NOT NULL CHECK (seat_no > 0),
    passenger_name   TEXT    NOT NULL,
    passenger_age    INTEGER NOT NULL CHECK (passenger_age BETWEEN 1 AND 120),
    passenger_gender TEXT    NOT NULL CHECK (passenger_gender IN ('M', 'F', 'O')),
    is_active        INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

-- The database itself guarantees no double booking: only ONE active row may
-- exist per (trip, seat). Cancelled seats (is_active = 0) are ignored, so the
-- seat becomes free again while the history is kept.
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_seat
    ON booking_seats (trip_id, seat_no)
    WHERE is_active = 1;

-- ---------------------------------------------------------------------------
-- Convenience view: every trip with route, bus and live seat availability
-- ---------------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_trip_availability AS
SELECT  t.trip_id,
        r.source,
        r.destination,
        t.departure_time,
        t.arrival_time,
        b.bus_number,
        b.bus_type,
        t.fare,
        b.total_seats,
        b.total_seats - COALESCE((SELECT COUNT(*)
                                  FROM booking_seats bs
                                  WHERE bs.trip_id = t.trip_id
                                    AND bs.is_active = 1), 0) AS seats_available
FROM    trips  t
JOIN    buses  b ON b.bus_id   = t.bus_id
JOIN    routes r ON r.route_id = t.route_id;
