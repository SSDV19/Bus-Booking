"""Business logic for the bus booking system.

All SQL lives in this module so the CLI stays free of database details.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime

from db import transaction

TIME_FMT = "%Y-%m-%d %H:%M"
PHONE_RE = re.compile(r"\d{10}")
GENDERS = {"M", "F", "O"}
MAX_SEATS_PER_BOOKING = 6


class BookingError(Exception):
    """A problem the user can fix (bad seat, wrong phone, trip departed...)."""


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def is_valid_phone(phone: str) -> bool:
    return bool(PHONE_RE.fullmatch(phone or ""))


def refund_rate(hours_before_departure: float) -> float:
    """Cancellation policy: 90% (24h+), 50% (6-24h), 0% (under 6h)."""
    if hours_before_departure >= 24:
        return 0.90
    if hours_before_departure >= 6:
        return 0.50
    return 0.0


# --------------------------------------------------------------------------
# searching
# --------------------------------------------------------------------------
def list_routes(conn):
    return conn.execute(
        "SELECT source, destination, distance_km FROM routes ORDER BY source, destination"
    ).fetchall()


def search_trips(conn, source, destination, travel_date, now=None):
    """Upcoming trips for a route on a date (YYYY-MM-DD), earliest first."""
    now_s = (now or datetime.now()).strftime(TIME_FMT)
    return conn.execute(
        """SELECT * FROM v_trip_availability
           WHERE LOWER(source) = LOWER(?)
             AND LOWER(destination) = LOWER(?)
             AND DATE(departure_time) = ?
             AND departure_time > ?
           ORDER BY departure_time""",
        (source.strip(), destination.strip(), travel_date, now_s),
    ).fetchall()


def get_trip(conn, trip_id):
    return conn.execute(
        "SELECT * FROM v_trip_availability WHERE trip_id = ?", (trip_id,)
    ).fetchone()


def taken_seats(conn, trip_id) -> set[int]:
    rows = conn.execute(
        "SELECT seat_no FROM booking_seats WHERE trip_id = ? AND is_active = 1",
        (trip_id,),
    ).fetchall()
    return {r["seat_no"] for r in rows}


# --------------------------------------------------------------------------
# booking
# --------------------------------------------------------------------------
def book_seats(conn, trip_id, name, phone, passengers, email=None, now=None) -> int:
    """Book seats atomically and return the new booking_id.

    `passengers` is a list of dicts:
        {"seat_no": 5, "name": "Asha", "age": 29, "gender": "F"}
    Either every seat is booked or nothing is.
    """
    now = now or datetime.now()
    now_s = now.strftime(TIME_FMT)

    # ---- validate input before touching the database ----
    name = (name or "").strip()
    if not name:
        raise BookingError("Customer name is required.")
    if not is_valid_phone(phone):
        raise BookingError("Phone number must be exactly 10 digits.")
    if not passengers:
        raise BookingError("Select at least one seat.")
    if len(passengers) > MAX_SEATS_PER_BOOKING:
        raise BookingError(f"You can book at most {MAX_SEATS_PER_BOOKING} seats at a time.")

    seat_nos = [p["seat_no"] for p in passengers]
    if len(set(seat_nos)) != len(seat_nos):
        raise BookingError("The same seat was selected more than once.")

    for p in passengers:
        p["gender"] = str(p.get("gender", "")).upper()
        if not str(p.get("name", "")).strip():
            raise BookingError("Every passenger needs a name.")
        if not isinstance(p.get("age"), int) or not 1 <= p["age"] <= 120:
            raise BookingError("Passenger age must be between 1 and 120.")
        if p["gender"] not in GENDERS:
            raise BookingError("Passenger gender must be M, F or O.")

    # ---- do the booking in one transaction ----
    try:
        with transaction(conn):
            trip = get_trip(conn, trip_id)
            if trip is None:
                raise BookingError("Trip not found.")
            if trip["departure_time"] <= now_s:
                raise BookingError("This trip has already departed.")

            bad = [s for s in seat_nos if not 1 <= s <= trip["total_seats"]]
            if bad:
                raise BookingError(
                    f"Invalid seat number(s) {bad}. This bus has seats 1-{trip['total_seats']}."
                )

            clash = sorted(set(seat_nos) & taken_seats(conn, trip_id))
            if clash:
                raise BookingError(f"Seat(s) {clash} already booked. Please choose others.")

            conn.execute(
                """INSERT INTO customers (name, phone, email) VALUES (?, ?, ?)
                   ON CONFLICT(phone) DO UPDATE
                       SET email = COALESCE(excluded.email, customers.email)""",
                (name, phone, email or None),
            )
            customer_id = conn.execute(
                "SELECT customer_id FROM customers WHERE phone = ?", (phone,)
            ).fetchone()[0]

            booking_id = conn.execute(
                """INSERT INTO bookings (customer_id, trip_id, booked_at, total_amount)
                   VALUES (?, ?, ?, ?)""",
                (
                    customer_id,
                    trip_id,
                    now.strftime("%Y-%m-%d %H:%M:%S"),
                    trip["fare"] * len(passengers),
                ),
            ).lastrowid

            conn.executemany(
                """INSERT INTO booking_seats
                       (booking_id, trip_id, seat_no,
                        passenger_name, passenger_age, passenger_gender)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (booking_id, trip_id, p["seat_no"], p["name"].strip(), p["age"], p["gender"])
                    for p in passengers
                ],
            )
        return booking_id
    except sqlite3.IntegrityError as exc:
        # Safety net: the unique index caught a race we didn't pre-check.
        raise BookingError("Seat was just taken by someone else. Please try again.") from exc


# --------------------------------------------------------------------------
# viewing and cancelling
# --------------------------------------------------------------------------
def get_booking(conn, booking_id):
    """Return {"booking": Row, "seats": [Row, ...]} or None."""
    header = conn.execute(
        """SELECT bk.*, c.name AS customer_name, c.phone,
                  r.source, r.destination, t.departure_time, t.arrival_time,
                  bu.bus_number, bu.bus_type
           FROM bookings bk
           JOIN customers c ON c.customer_id = bk.customer_id
           JOIN trips     t ON t.trip_id     = bk.trip_id
           JOIN routes    r ON r.route_id    = t.route_id
           JOIN buses    bu ON bu.bus_id     = t.bus_id
           WHERE bk.booking_id = ?""",
        (booking_id,),
    ).fetchone()
    if header is None:
        return None
    seats = conn.execute(
        """SELECT seat_no, passenger_name, passenger_age, passenger_gender
           FROM booking_seats WHERE booking_id = ? ORDER BY seat_no""",
        (booking_id,),
    ).fetchall()
    return {"booking": header, "seats": seats}


def bookings_for_phone(conn, phone):
    return conn.execute(
        """SELECT bk.booking_id, r.source || ' -> ' || r.destination AS route,
                  t.departure_time, bk.status, bk.total_amount,
                  (SELECT COUNT(*) FROM booking_seats s WHERE s.booking_id = bk.booking_id) AS seats
           FROM bookings bk
           JOIN customers c ON c.customer_id = bk.customer_id
           JOIN trips     t ON t.trip_id     = bk.trip_id
           JOIN routes    r ON r.route_id    = t.route_id
           WHERE c.phone = ?
           ORDER BY t.departure_time DESC""",
        (phone,),
    ).fetchall()


def cancel_booking(conn, booking_id, phone, now=None) -> float:
    """Cancel a whole booking, free its seats, and return the refund amount."""
    now = now or datetime.now()

    with transaction(conn):
        row = conn.execute(
            """SELECT bk.status, bk.total_amount, t.departure_time, c.phone
               FROM bookings bk
               JOIN trips     t ON t.trip_id     = bk.trip_id
               JOIN customers c ON c.customer_id = bk.customer_id
               WHERE bk.booking_id = ?""",
            (booking_id,),
        ).fetchone()

        # Same message for "missing" and "wrong phone" so IDs can't be probed.
        if row is None or row["phone"] != phone:
            raise BookingError("No booking found for that ID and phone number.")
        if row["status"] == "CANCELLED":
            raise BookingError("This booking is already cancelled.")

        departure = datetime.strptime(row["departure_time"], TIME_FMT)
        hours_left = (departure - now).total_seconds() / 3600
        if hours_left <= 0:
            raise BookingError("This trip has already departed and cannot be cancelled.")

        refund = round(row["total_amount"] * refund_rate(hours_left), 2)

        conn.execute(
            """UPDATE bookings
               SET status = 'CANCELLED', refund_amount = ?, cancelled_at = ?
               WHERE booking_id = ?""",
            (refund, now.strftime("%Y-%m-%d %H:%M:%S"), booking_id),
        )
        conn.execute(
            "UPDATE booking_seats SET is_active = 0 WHERE booking_id = ?", (booking_id,)
        )
    return refund


# --------------------------------------------------------------------------
# admin reports
# --------------------------------------------------------------------------
def revenue_by_route(conn):
    return conn.execute(
        """SELECT r.source, r.destination,
                  SUM(bk.status = 'CONFIRMED') AS confirmed,
                  SUM(bk.status = 'CANCELLED') AS cancelled,
                  ROUND(SUM(bk.total_amount - bk.refund_amount), 2) AS net_revenue
           FROM bookings bk
           JOIN trips  t ON t.trip_id  = bk.trip_id
           JOIN routes r ON r.route_id = t.route_id
           GROUP BY r.route_id
           ORDER BY net_revenue DESC"""
    ).fetchall()


def busiest_trips(conn, now=None, limit=10):
    now_s = (now or datetime.now()).strftime(TIME_FMT)
    return conn.execute(
        """SELECT trip_id, source, destination, departure_time, total_seats,
                  total_seats - seats_available AS booked,
                  ROUND(100.0 * (total_seats - seats_available) / total_seats, 1) AS occupancy_pct
           FROM v_trip_availability
           WHERE departure_time > ?
           ORDER BY occupancy_pct DESC, departure_time
           LIMIT ?""",
        (now_s, limit),
    ).fetchall()
