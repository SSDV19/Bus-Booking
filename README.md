# Bus Booking System (Python + SQL)

A command-line bus ticket booking app built with **Python 3** and **SQLite**.
No third-party packages are needed, because `sqlite3` ships with Python.

## Run it

```bash
python main.py            # first run creates bus_booking.db with sample data
python main.py --reset    # wipe the database and regenerate a fresh week of trips
python -m unittest -v     # run the tests
```

## Features

- Search buses by source, destination and date, with live seat availability
- Visual seat map, then book up to 6 seats with passenger details
- View a booking (ticket) by ID, or list all bookings for a phone number
- Cancel a booking with a tiered refund: 90% at 24h+ before departure, 50% at 6-24h, 0% under 6h
- Admin reports: net revenue per route, fullest upcoming trips

## Project layout

| File | Purpose |
|------|---------|
| `schema.sql` | Tables, constraints, indexes and the `v_trip_availability` view |
| `db.py` | Connection setup and the `transaction()` helper |
| `seed.py` | Sample routes, buses and 7 days of trips |
| `booking.py` | Business logic: search, book, cancel, reports (all SQL is here) |
| `main.py` | Interactive menu (input/output only) |
| `test_booking.py` | Unit tests |
| `queries.sql` | Extra SQL to explore the data (JOIN, GROUP BY/HAVING, LEFT JOIN) |

## Database design

```
routes ──< trips >── buses
             │
             └──< bookings >── customers
                     │
                     └──< booking_seats
```

- **routes / buses / trips**: a trip is one bus running one route at one time, with a fare.
- **customers**: identified by a unique phone number.
- **bookings**: one per purchase, with `status` (CONFIRMED / CANCELLED), amount and refund.
- **booking_seats**: one row per passenger and seat.

## Key design decisions (good viva / interview talking points)

1. **No double booking, enforced by the database.** A *partial unique index*
   `UNIQUE (trip_id, seat_no) WHERE is_active = 1` allows only one active holder per seat.
   Cancelled seats are set to `is_active = 0`, so they become free again while history is kept.
2. **Atomic bookings.** `book_seats` runs inside `BEGIN IMMEDIATE ... COMMIT`.
   If any seat in the request is taken, nothing is saved.
3. **Soft cancel, not delete.** Cancelled bookings stay in the table, which is what makes the revenue and cancellation reports possible.
4. **A view for availability.** `v_trip_availability` computes free seats once, and both search and reports reuse it.
5. **Parameterized queries everywhere** (`?` placeholders), so there is no SQL injection.
6. **Layered code.** `main.py` never touches SQL, so the CLI can be swapped for Flask or FastAPI without changing `booking.py`.

## Ideas to extend it

- A `payments` table (UPI / card / wallet) and payment status
- Partial cancellation (cancel one seat instead of the whole booking)
- Bus rotation: stop the same bus being scheduled on overlapping trips
- Admin menu to add buses, routes and trips
- A web front end with Flask or FastAPI on top of `booking.py`
- Move to MySQL or PostgreSQL: the schema changes are small (`AUTOINCREMENT` → `AUTO_INCREMENT` / `SERIAL`, and use `SELECT ... FOR UPDATE` instead of `BEGIN IMMEDIATE`)
