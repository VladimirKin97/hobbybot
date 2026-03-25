import asyncpg
import logging
from datetime import datetime
from math import radians, sin, cos, acos
from config import DATABASE_URL

db_pool = None

async def init_db_pool():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=5, max_size=20, command_timeout=60)
        logging.info("Пул підключень до БД створено.")
        async with db_pool.acquire() as conn:
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id SERIAL PRIMARY KEY, event_id INT NOT NULL, seeker_id BIGINT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', message TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(event_id, seeker_id)
            );
            """)
            try:
                await conn.execute("ALTER TABLE requests ADD COLUMN message TEXT;")
            except asyncpg.exceptions.DuplicateColumnError: pass

async def get_user_from_db(user_id: int):
    async with db_pool.acquire() as conn: return await conn.fetchrow("SELECT * FROM users WHERE telegram_id::text = $1", str(user_id))

async def save_user_to_db(user_id, phone, name, city, photo, interests):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (telegram_id, phone, name, city, photo, interests) VALUES ($1,$2,$3,$4,$5,$6)
            ON CONFLICT (telegram_id) DO UPDATE SET phone=EXCLUDED.phone, name=EXCLUDED.name, city=EXCLUDED.city, photo=EXCLUDED.photo, interests=EXCLUDED.interests
        """, user_id, phone, name, city, photo, interests)

async def save_event_to_db(user_id, creator_name, creator_phone, title, description, date, location, capacity, needed_count, status, location_lat, location_lon, photo):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("""
            INSERT INTO events (user_id, creator_name, creator_phone, title, description, date, location, capacity, needed_count, status, location_lat, location_lon, photo) 
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) RETURNING *
        """, user_id, creator_name or '', creator_phone or '', title, description, date, location, capacity, needed_count, status, location_lat, location_lon, photo)

async def get_organizer_avg_rating(organizer_id: int):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT AVG(score)::float AS avg FROM ratings WHERE organizer_id=$1 AND status='done' AND score IS NOT NULL", organizer_id)
        return row["avg"] if row and row["avg"] else None

async def find_events_near(lat: float, lon: float, radius_km: float, limit: int = 10):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            WITH params AS (SELECT $1::float AS lat, $2::float AS lon, $3::float AS r)
            SELECT e.*, u.name AS organizer_name, (SELECT AVG(score)::float FROM ratings WHERE organizer_id = e.user_id AND status='done') as org_rating
            FROM events e JOIN params p ON true LEFT JOIN users u ON u.telegram_id::text = e.user_id::text
            WHERE TRIM(LOWER(e.status))='active' AND e.location_lat IS NOT NULL AND e.location_lon IS NOT NULL AND e.date >= now()
              AND (6371 * acos(cos(radians(p.lat)) * cos(radians(e.location_lat)) * cos(radians(e.location_lon) - radians(p.lon)) + sin(radians(p.lat)) * sin(radians(e.location_lat)))) <= p.r
            ORDER BY (6371 * acos(cos(radians(p.lat)) * cos(radians(e.location_lat)) * cos(radians(e.location_lon) - radians(p.lon)) + sin(radians(p.lat)) * sin(radians(e.location_lat)))) ASC LIMIT $4
        """, lat, lon, radius_km, limit)

async def find_events_by_kw(keyword: str, limit: int = 10):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT e.*, u.name AS organizer_name, (SELECT AVG(score)::float FROM ratings WHERE organizer_id = e.user_id AND status='done') as org_rating
            FROM events e LEFT JOIN users u ON u.telegram_id::text = e.user_id::text
            WHERE TRIM(LOWER(e.status))='active' AND (e.title ILIKE $1 OR e.description ILIKE $1) AND e.date >= now()
            ORDER BY e.date ASC LIMIT $2
        """, f"%{keyword}%", limit)

async def get_events_for_swipe(city: str, limit: int = 50):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT e.*, u.name AS organizer_name, (SELECT AVG(score)::float FROM ratings WHERE organizer_id = e.user_id AND status='done') as org_rating
            FROM events e LEFT JOIN users u ON u.telegram_id::text = e.user_id::text
            WHERE TRIM(LOWER(e.status))='active' AND e.location ILIKE $1 AND e.date >= now()
            ORDER BY e.date ASC LIMIT $2
        """, f"%{city}%", limit)

async def list_user_events(user_id: int, filter_kind: str | None = None):
    async with db_pool.acquire() as conn:
        if filter_kind: return await conn.fetch("SELECT * FROM events WHERE user_id::text = $1 AND TRIM(LOWER(status)) = $2 AND date >= now() - interval '1 month' ORDER BY date DESC", str(user_id), filter_kind.lower())
        return await conn.fetch("SELECT * FROM events WHERE user_id::text = $1 AND date >= now() - interval '1 month' ORDER BY date DESC", str(user_id))

# === ОСЬ ТУТ ВИПРАВЛЕНО БАГ З "НЕВІДОМИМ" ===
async def get_event_by_id(event_id: int):
    async with db_pool.acquire() as conn: 
        return await conn.fetchrow("""
            SELECT e.*, u.name AS organizer_name, 
                   (SELECT AVG(score)::float FROM ratings WHERE organizer_id = e.user_id AND status='done') as org_rating
            FROM events e 
            LEFT JOIN users u ON u.telegram_id::text = e.user_id::text 
            WHERE e.id = $1
        """, event_id)

async def create_join_request(event_id: int, user_id: int, message: str):
    async with db_pool.acquire() as conn:
        try:
            row = await conn.fetchrow("INSERT INTO requests (event_id, seeker_id, status, message) VALUES ($1, $2, 'pending', $3) RETURNING id", event_id, user_id, message)
            return row['id'] if row else None
        except asyncpg.exceptions.UniqueViolationError: return -1

async def get_request_info(req_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("""
            SELECT r.*, e.user_id as organizer_id, e.title as event_title, e.needed_count, u.name as seeker_name
            FROM requests r JOIN events e ON r.event_id = e.id JOIN users u ON r.seeker_id::text = u.telegram_id::text WHERE r.id = $1
        """, req_id)

async def get_request_by_event_and_user(event_id: int, user_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM requests WHERE event_id = $1 AND seeker_id = $2", event_id, user_id)

async def update_request_status_db(req_id: int, status: str):
    async with db_pool.acquire() as conn: await conn.execute("UPDATE requests SET status = $1 WHERE id = $2", status, req_id)

async def decrement_needed_count(event_id: int):
    async with db_pool.acquire() as conn: await conn.execute("UPDATE events SET needed_count = GREATEST(needed_count - 1, 0) WHERE id = $1", event_id)

async def get_user_participations(user_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT e.*, r.status as req_status FROM events e JOIN requests r ON e.id = r.event_id 
            WHERE r.seeker_id::text = $1 AND r.status != 'rejected' AND r.status != 'cancelled' AND e.date >= now() - interval '1 month' ORDER BY e.date DESC
        """, str(user_id))

async def get_approved_participants(event_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT u.name, u.telegram_id FROM requests r JOIN users u ON r.seeker_id::text = u.telegram_id::text 
            WHERE r.event_id = $1 AND r.status = 'approved'
        """, event_id)

async def cancel_event_db(event_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE events SET status = 'deleted' WHERE id = $1", event_id)

async def cancel_request_db(req_id: int, event_id: int, was_approved: bool):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE requests SET status = 'cancelled' WHERE id = $1", req_id)
        if was_approved:
            await conn.execute("UPDATE events SET needed_count = needed_count + 1 WHERE id = $1", event_id)
