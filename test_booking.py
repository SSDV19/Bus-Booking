"""Run with:  python -m unittest -v"""
import sqlite3
import unittest
from datetime import datetime

import booking
import db

NOW = datetime(2026, 10, 1, 10, 0)  # fixed "current time" for repeatable tests


def person(seat, name="Asha"):
    return {"seat_no": seat, "name": name, "age": 30, "gender": "F"}


class BookingTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.get_connection(":memory:")
        db.init_db(self.conn)
        self.conn.executescript(
            """
            INSERT INTO buses  (bus_id, bus_number, bus_type, total_seats)
                VALUES (1, 'TN01-TEST', 'AC Seater', 10);
            INSERT INTO routes (route_id, source, destination, distance_km)
                VALUES (1, 'Chennai', 'Madurai', 460);
            INSERT INTO trips  (trip_id, bus_id, route_id, departure_time, arrival_time, fare)
                VALUES (1, 1, 1, '2026-10-05 21:00', '2026-10-06 05:00', 500);
            """
        )

    def book(self, seats, phone="9876543210", now=NOW):
        return booking.book_seats(
            self.conn, 1, "Asha", phone, [person(s) for s in seats], now=now
        )

    def free_seats(self):
        return booking.get_trip(self.conn, 1)["seats_available"]

    # ---- happy path --------------------------------------------------
    def test_booking_reduces_availability_and_totals_fare(self):
        booking_id = self.book([1, 2])
        data = booking.get_booking(self.conn, booking_id)
        self.assertEqual(data["booking"]["total_amount"], 1000)
        self.assertEqual([s["seat_no"] for s in data["seats"]], [1, 2])
        self.assertEqual(self.free_seats(), 8)

    def test_search_finds_trip_and_ignores_departed_ones(self):
        found = booking.search_trips(self.conn, "chennai", "MADURAI", "2026-10-05", now=NOW)
        self.assertEqual(len(found), 1)
        later = datetime(2026, 10, 5, 22, 0)
        self.assertEqual(booking.search_trips(self.conn, "Chennai", "Madurai", "2026-10-05", now=later), [])

    # ---- double booking ----------------------------------------------
    def test_same_seat_cannot_be_booked_twice(self):
        self.book([3])
        with self.assertRaises(booking.BookingError):
            self.book([3], phone="9123456780")
        self.assertEqual(self.free_seats(), 9)

    def test_conflict_rolls_back_the_whole_booking(self):
        self.book([4])
        with self.assertRaises(booking.BookingError):
            self.book([3, 4], phone="9123456780")  # 4 is taken -> 3 must not be booked either
        self.assertNotIn(3, booking.taken_seats(self.conn, 1))
        count = self.conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
        self.assertEqual(count, 1)

    def test_database_itself_blocks_duplicate_active_seats(self):
        self.book([5])
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """INSERT INTO booking_seats
                   (booking_id, trip_id, seat_no, passenger_name, passenger_age, passenger_gender)
                   VALUES (1, 1, 5, 'Hacker', 40, 'M')"""
            )

    # ---- validation --------------------------------------------------
    def test_invalid_input_is_rejected(self):
        with self.assertRaises(booking.BookingError):
            self.book([11])                       # bus only has 10 seats
        with self.assertRaises(booking.BookingError):
            self.book([1], phone="12345")         # bad phone
        with self.assertRaises(booking.BookingError):
            self.book([1, 1])                     # duplicate seat in request
        with self.assertRaises(booking.BookingError):
            self.book([1], now=datetime(2026, 10, 6))  # trip already departed

    # ---- cancellation ------------------------------------------------
    def test_early_cancel_refunds_90_percent_and_frees_seats(self):
        booking_id = self.book([1, 2])
        refund = booking.cancel_booking(self.conn, booking_id, "9876543210", now=NOW)
        self.assertEqual(refund, 900)
        self.assertEqual(self.free_seats(), 10)
        self.book([1], phone="9123456780")        # seat 1 can be booked again

    def test_refund_tiers(self):
        for now, expected in [
            (datetime(2026, 10, 5, 15, 0), 250),  # 6h before  -> 50%
            (datetime(2026, 10, 5, 19, 0), 0),    # 2h before  -> 0%
        ]:
            with self.subTest(now=now):
                booking_id = self.book([1], now=NOW)
                self.assertEqual(
                    booking.cancel_booking(self.conn, booking_id, "9876543210", now=now),
                    expected,
                )

    def test_cancel_requires_matching_phone_and_only_once(self):
        booking_id = self.book([1])
        with self.assertRaises(booking.BookingError):
            booking.cancel_booking(self.conn, booking_id, "9000000000", now=NOW)
        booking.cancel_booking(self.conn, booking_id, "9876543210", now=NOW)
        with self.assertRaises(booking.BookingError):
            booking.cancel_booking(self.conn, booking_id, "9876543210", now=NOW)

    # ---- reports -----------------------------------------------------
    def test_revenue_report_is_net_of_refunds(self):
        self.book([1])                                  # Rs.500 stays
        cancelled = self.book([2], phone="9123456780")  # Rs.500 booked, 90% refunded
        booking.cancel_booking(self.conn, cancelled, "9123456780", now=NOW)
        row = booking.revenue_by_route(self.conn)[0]
        self.assertEqual((row["confirmed"], row["cancelled"], row["net_revenue"]), (1, 1, 550))


if __name__ == "__main__":
    unittest.main()
