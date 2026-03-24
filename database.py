import asyncpg
import logging
from datetime import datetime, timedelta, timezone
from math import radians, sin, cos, acos
from config import DATABASE_URL

db_pool = None

async def init_db_pool():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=5, max_size=20, command_timeout=60)
        logging.info("Пул підключень до БД створено.")

async def get_user_from_db(user_id: int) -> asyncpg.Record | None:
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE telegram_id::text = $1", str(user_id))

async def save_user_to_db(user_id: int, phone: str, name: str, city: str, photo: str, interests: str):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (telegram_id, phone, name, city, photo, interests)
            VALUES ($1,$2,$3,$4,$5,$6)
            ON CONFLICT (telegram_id) DO UPDATE SET
              phone=EXCLUDED.phone, name=EXCLUDED.name, city=EXCLUDED.city,
              photo=EXCLUDED.photo, interests=EXCLUDED.interests
        """, user_id, phone, name, city, photo, interests)

async def save_event_to_db(user_id: int, creator_name: str, creator_phone: str, title: str, description: str, date: datetime, location: str, capacity: int, needed_count: int, status: str, location_lat: float | None = None, location_lon: float | None = None, photo: str | None = None):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("""
            INSERT INTO events (
                user_id, creator_name, creator_phone, title, description, date, location, capacity, needed_count, status, location_lat, location_lon, photo
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            RETURNING *
        """, user_id, creator_name or '', creator_phone or '', title, description, date, location, capacity, needed_count, status, location_lat, location_lon, photo)

async def update_event_field(event_id: int, owner_id: int, field: str, value):
    whitelist = {"title": "text", "description": "text", "date": "timestamp", "location": "text", "capacity": "int", "needed_count": "int", "photo": "text", "status": "text"}
    if field not in whitelist: raise ValueError("field not allowed")
    async with db_pool.acquire() as conn:
        res = await conn.execute(f"UPDATE events SET {field}=$3 WHERE id=$1 AND user_id::text=$2", event_id, str(owner_id), value)
        return res.startswith("UPDATE")

async def get_organizer_avg_rating(organizer_id: int) -> float | None:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT AVG(score)::float AS avg FROM ratings WHERE organizer_id=$1 AND status='done' AND score IS NOT NULL", organizer_id)
        return row["avg"] if row else None

async def find_events_near(lat: float, lon: float, radius_km: float, limit: int = 10):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            WITH params AS (SELECT $1::float AS lat, $2::float AS lon, $3::float AS r)
            SELECT e.*, u.name AS organizer_name
            FROM events e JOIN params p ON true LEFT JOIN users u ON u.telegram_id::text = e.user_id::text
            WHERE TRIM(LOWER(e.status))='active' AND e.location_lat IS NOT NULL AND e.location_lon IS NOT NULL AND e.date >= now()
              AND (6371 * acos(cos(radians(p.lat)) * cos(radians(e.location_lat)) * cos(radians(e.location_lon) - radians(p.lon)) + sin(radians(p.lat)) * sin(radians(e.location_lat)))) <= p.r
            ORDER BY (6371 * acos(cos(radians(p.lat)) * cos(radians(e.location_lat)) * cos(radians(e.location_lon) - radians(p.lon)) + sin(radians(p.lat)) * sin(radians(e.location_lat)))) ASC LIMIT $4
        """, lat, lon, radius_km, limit)

async def find_events_by_kw(keyword: str, limit: int = 10):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT e.*, u.name AS organizer_name
            FROM events e LEFT JOIN users u ON u.telegram_id::text = e.user_id::text
            WHERE TRIM(LOWER(e.status))='active' AND (e.title ILIKE $1 OR e.description ILIKE $1) AND e.date >= now()
            ORDER BY e.date ASC LIMIT $2
        """, f"%{keyword}%", limit)

async def get_events_for_swipe(city: str, limit: int = 50):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT e.*, u.name AS organizer_name
            FROM events e LEFT JOIN users u ON u.telegram_id::text = e.user_id::text
            WHERE TRIM(LOWER(e.status))='active' AND e.location ILIKE $1 AND e.date >= now()
            ORDER BY e.date ASC LIMIT $2
        """, f"%{city}%", limit)

async def list_user_events(user_id: int, filter_kind: str | None = None):
    async with db_pool.acquire() as conn:
        if filter_kind:
            return await conn.fetch("SELECT * FROM events WHERE user_id::text = $1 AND TRIM(LOWER(status)) = $2 ORDER BY date DESC", str(user_id), filter_kind.lower())
        return await conn.fetch("SELECT * FROM events WHERE user_id::text = $1 ORDER BY date DESC", str(user_id))
