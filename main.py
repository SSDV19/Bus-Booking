#!/usr/bin/env python3
"""Command-line interface for the bus booking system.

Run:   python main.py            (start the app)
       python main.py --reset    (delete the database and re-create sample data)
"""
import argparse
from datetime import date, datetime

import booking
import db
import seed


# --------------------------------------------------------------------------
# input / output helpers
# --------------------------------------------------------------------------
def ask(prompt, cast=str, check=None, error="Invalid input, please try again.", default=None):
    """Keep asking until the answer converts with `cast` and passes `check`."""
    suffix = f" [{default}]" if default is not None else ""
    while True:
        raw = input(f"{prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        try:
            value = cast(raw)
            if check is None or check(value):
                return value
        except ValueError:
            pass
        print(error)


def parse_date(text):
    return datetime.strptime(text, "%Y-%m-%d").date().isoformat()


def parse_seats(text):
    return [int(part) for part in text.replace(" ", "").split(",") if part]


def print_rows(rows):
    """Print sqlite3.Row objects as an aligned table."""
    if not rows:
        print("  (no data)")
        return
    headers = rows[0].keys()
    widths = [max(len(h), *(len(str(r[h])) for r in rows)) for h in headers]
    print("  " + " | ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("  " + "-+-".join("-" * w for w in widths))
    for r in rows:
        print("  " + " | ".join(str(r[h]).ljust(w) for h, w in zip(headers, widths)))


def show_trips(trips):
    print(f"\n{'ID':<5}{'Departs':<18}{'Arrives':<18}{'Bus':<15}{'Type':<16}{'Fare':>8}{'Free':>6}")
    print("-" * 86)
    for t in trips:
        print(
            f"{t['trip_id']:<5}{t['departure_time']:<18}{t['arrival_time']:<18}"
            f"{t['bus_number']:<15}{t['bus_type']:<16}{t['fare']:>8.0f}{t['seats_available']:>6}"
        )


def show_seat_map(total, taken):
    print("\n  Seat map  ([nn] = free, XX = booked)")
    for first in range(1, total + 1, 4):
        cells = [" XX " if s in taken else f"[{s:02d}]" for s in range(first, min(first + 4, total + 1))]
        print(f"   {' '.join(cells[:2])}   ||   {' '.join(cells[2:])}")


def show_ticket(data):
    b, seats = data["booking"], data["seats"]
    print("\n" + "=" * 46)
    print(f"  BOOKING #{b['booking_id']}   [{b['status']}]")
    print("=" * 46)
    print(f"  Route     : {b['source']} -> {b['destination']}")
    print(f"  Departure : {b['departure_time']}")
    print(f"  Arrival   : {b['arrival_time']}")
    print(f"  Bus       : {b['bus_number']} ({b['bus_type']})")
    print(f"  Booked by : {b['customer_name']} ({b['phone']})")
    print("  Passengers:")
    for s in seats:
        print(f"    Seat {s['seat_no']:>2}  {s['passenger_name']}, {s['passenger_age']}, {s['passenger_gender']}")
    print(f"  Amount    : Rs. {b['total_amount']:.2f}")
    if b["status"] == "CANCELLED":
        print(f"  Refunded  : Rs. {b['refund_amount']:.2f}")
    print("=" * 46)


# --------------------------------------------------------------------------
# menu actions
# --------------------------------------------------------------------------
def search_flow(conn):
    routes = booking.list_routes(conn)
    print("\nAvailable routes: " + ", ".join(f"{r['source']}->{r['destination']}" for r in routes))
    source = ask("From city", check=bool)
    destination = ask("To city", check=bool)
    travel_date = ask("Travel date (YYYY-MM-DD)", parse_date,
                      error="Use the format YYYY-MM-DD.", default=date.today().isoformat())
    trips = booking.search_trips(conn, source, destination, travel_date)
    if trips:
        show_trips(trips)
    else:
        print("\nNo upcoming buses found for that route and date.")
    return trips


def book_flow(conn):
    trips = search_flow(conn)
    if not trips:
        return

    valid_ids = {t["trip_id"] for t in trips}
    trip_id = ask("\nTrip ID to book (0 to go back)", int,
                  check=lambda x: x == 0 or x in valid_ids, error="Pick an ID from the list.")
    if trip_id == 0:
        return

    trip = booking.get_trip(conn, trip_id)
    taken = booking.taken_seats(conn, trip_id)
    show_seat_map(trip["total_seats"], taken)

    seats = ask(
        "\nSeat numbers, comma separated (e.g. 5,6)",
        parse_seats,
        check=lambda s: (
            0 < len(s) <= booking.MAX_SEATS_PER_BOOKING
            and len(set(s)) == len(s)
            and all(1 <= n <= trip["total_seats"] and n not in taken for n in s)
        ),
        error=f"Choose free seats from the map (max {booking.MAX_SEATS_PER_BOOKING}, no repeats).",
    )

    passengers = []
    for seat in seats:
        print(f"\nPassenger for seat {seat}")
        passengers.append({
            "seat_no": seat,
            "name": ask("  Name", check=bool),
            "age": ask("  Age", int, lambda a: 1 <= a <= 120, "Enter an age from 1 to 120."),
            "gender": ask("  Gender (M/F/O)", lambda s: s.upper(),
                          lambda g: g in booking.GENDERS, "Enter M, F or O."),
        })

    print("\nContact details")
    name = ask("  Your name", check=bool)
    phone = ask("  Phone (10 digits)", check=booking.is_valid_phone, error="Enter exactly 10 digits.")
    email = ask("  Email (optional)", default="")

    total = trip["fare"] * len(passengers)
    if ask(f"\nTotal Rs. {total:.2f}. Confirm booking? (y/n)", lambda s: s.lower(),
           lambda a: a in ("y", "n"), "Type y or n.") == "n":
        print("Booking cancelled.")
        return

    try:
        booking_id = booking.book_seats(conn, trip_id, name, phone, passengers, email or None)
    except booking.BookingError as exc:
        print(f"\nCould not book: {exc}")
        return
    print("\nBooking confirmed!")
    show_ticket(booking.get_booking(conn, booking_id))


def view_flow(conn):
    booking_id = ask("Booking ID", int)
    data = booking.get_booking(conn, booking_id)
    if data is None:
        print("No such booking.")
    else:
        show_ticket(data)


def cancel_flow(conn):
    booking_id = ask("Booking ID to cancel", int)
    phone = ask("Phone number used for booking", check=booking.is_valid_phone,
                error="Enter exactly 10 digits.")
    try:
        refund = booking.cancel_booking(conn, booking_id, phone)
    except booking.BookingError as exc:
        print(f"\nCould not cancel: {exc}")
        return
    print(f"\nBooking #{booking_id} cancelled. Refund: Rs. {refund:.2f}")
    print("(Policy: 90% if 24h+ before departure, 50% if 6-24h, otherwise none.)")


def my_bookings_flow(conn):
    phone = ask("Phone number", check=booking.is_valid_phone, error="Enter exactly 10 digits.")
    print()
    print_rows(booking.bookings_for_phone(conn, phone))


def reports_flow(conn):
    print("\nNet revenue by route:")
    print_rows(booking.revenue_by_route(conn))
    print("\nFullest upcoming trips:")
    print_rows(booking.busiest_trips(conn, limit=5))


MENU = {
    "1": ("Search buses", lambda c: search_flow(c)),
    "2": ("Book tickets", book_flow),
    "3": ("View a booking", view_flow),
    "4": ("Cancel a booking", cancel_flow),
    "5": ("My bookings (by phone)", my_bookings_flow),
    "6": ("Admin reports", reports_flow),
    "0": ("Exit", None),
}


def main():
    parser = argparse.ArgumentParser(description="Bus booking system")
    parser.add_argument("--reset", action="store_true",
                        help="delete the database and re-create sample data")
    args = parser.parse_args()

    if args.reset and db.DB_PATH.exists():
        db.DB_PATH.unlink()

    conn = db.get_connection()
    db.init_db(conn)
    if seed.seed(conn):
        print("Created sample buses, routes and trips.")

    try:
        while True:
            print("\n=== BUS BOOKING SYSTEM ===")
            for key, (label, _) in MENU.items():
                print(f"  {key}. {label}")
            choice = input("Choose an option: ").strip()
            if choice == "0":
                break
            if choice in MENU:
                MENU[choice][1](conn)
            else:
                print("Please choose a number from the menu.")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        conn.close()
    print("\nGoodbye!")


if __name__ == "__main__":
    main()
