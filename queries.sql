-- Handy queries for exploring the data.
-- Run with:  sqlite3 bus_booking.db < queries.sql
.headers on
.mode column

-- 1. Upcoming trips on a route with free seats (uses the view)
SELECT trip_id, departure_time, bus_type, fare, seats_available
FROM   v_trip_availability
WHERE  source = 'Chennai' AND destination = 'Bengaluru'
  AND  departure_time > datetime('now', 'localtime')
ORDER  BY departure_time
LIMIT  5;

-- 2. Which seats are booked on trip 1, and by whom?
SELECT bs.seat_no, bs.passenger_name, c.name AS booked_by, bk.status
FROM   booking_seats bs
JOIN   bookings  bk ON bk.booking_id  = bs.booking_id
JOIN   customers c  ON c.customer_id  = bk.customer_id
WHERE  bs.trip_id = 1 AND bs.is_active = 1
ORDER  BY bs.seat_no;

-- 3. Customers who have spent more than Rs.2000 in total (GROUP BY + HAVING)
SELECT c.name, c.phone,
       COUNT(bk.booking_id)                     AS bookings,
       SUM(bk.total_amount - bk.refund_amount)  AS net_spent
FROM   customers c
JOIN   bookings  bk ON bk.customer_id = c.customer_id
GROUP  BY c.customer_id
HAVING net_spent > 2000
ORDER  BY net_spent DESC;

-- 4. Cancellation rate per route
SELECT r.source || ' -> ' || r.destination                     AS route,
       COUNT(*)                                                 AS bookings,
       SUM(bk.status = 'CANCELLED')                             AS cancelled,
       ROUND(100.0 * SUM(bk.status = 'CANCELLED') / COUNT(*), 1) AS cancel_pct
FROM   bookings bk
JOIN   trips  t ON t.trip_id  = bk.trip_id
JOIN   routes r ON r.route_id = t.route_id
GROUP  BY r.route_id
ORDER  BY cancel_pct DESC;

-- 5. Trips with no bookings at all (LEFT JOIN + IS NULL)
SELECT t.trip_id, t.departure_time
FROM   trips t
LEFT   JOIN bookings bk ON bk.trip_id = t.trip_id
WHERE  bk.booking_id IS NULL
LIMIT  10;
