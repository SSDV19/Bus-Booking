"""Sample data: routes, buses and a week of upcoming trips."""
from datetime import date, datetime, time, timedelta

from db import transaction

# (source, destination, distance_km)
ROUTES = [
    ("Chennai", "Bengaluru", 350),
    ("Bengaluru", "Chennai", 350),
    ("Chennai", "Coimbatore", 500),
    ("Coimbatore", "Chennai", 500),
    ("Chennai", "Madurai", 460),
    ("Madurai", "Chennai", 460),
    ("Bengaluru", "Hyderabad", 570),
    ("Hyderabad", "Bengaluru", 570),
]

# (bus_type, total_seats, fare per km in rupees)
BUS_TYPES = [
    ("AC Sleeper", 30, 2.0),
    ("Non-AC Sleeper", 30, 1.4),
    ("AC Seater", 40, 1.6),
    ("Non-AC Seater", 40, 1.0),
]

DEPARTURES = [time(8, 0), time(21, 30)]  # two trips per route per day
AVG_SPEED_KMPH = 45


def seed(conn, days=7, start=None):
    """Fill an empty database. Returns False if data already exists."""
    if conn.execute("SELECT COUNT(*) FROM buses").fetchone()[0]:
        return False

    start = start or date.today()

    with transaction(conn):
        for r_idx, (src, dst, km) in enumerate(ROUTES):
            route_id = conn.execute(
                "INSERT INTO routes (source, destination, distance_km) VALUES (?, ?, ?)",
                (src, dst, km),
            ).lastrowid

            for slot, dep_clock in enumerate(DEPARTURES):
                bus_type, seats, rate = BUS_TYPES[(r_idx + slot) % len(BUS_TYPES)]
                bus_id = conn.execute(
                    "INSERT INTO buses (bus_number, bus_type, total_seats) VALUES (?, ?, ?)",
                    (f"TN{10 + r_idx}-BX-{1000 + r_idx * 2 + slot}", bus_type, seats),
                ).lastrowid

                fare = round(km * rate / 10) * 10  # nearest Rs.10
                duration = timedelta(minutes=round(km / AVG_SPEED_KMPH * 60))

                for d in range(days):
                    dep = datetime.combine(start + timedelta(days=d), dep_clock)
                    conn.execute(
                        """INSERT INTO trips
                               (bus_id, route_id, departure_time, arrival_time, fare)
                           VALUES (?, ?, ?, ?, ?)""",
                        (
                            bus_id,
                            route_id,
                            dep.strftime("%Y-%m-%d %H:%M"),
                            (dep + duration).strftime("%Y-%m-%d %H:%M"),
                            fare,
                        ),
                    )
    return True
