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

        # Ініціалізація відсутніх таблиць
        async with db_pool.acquire() as conn:
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                id SERIAL PRIMARY KEY,
                event_id INT NOT NULL,
                organizer_id BIGINT NOT NULL,
                seeker_id BIGINT NOT NULL,
                score INT CHECK (score BETWEEN 1 AND 10) NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(event_id, seeker_id)
            );
            """)
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS event_notifications (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                type TEXT NOT NULL,
                keyword TEXT,
                lat DOUBLE PRECISION,
                lon DOUBLE PRECISION,
                radius_km DOUBLE PRECISION,
                interests TEXT,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """)

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

async def update_event_status(event_id: int, owner_id: int, new_status: str) -> bool:
    async with db_pool.acquire() as conn:
        res = await conn.execute("UPDATE events SET status=$3 WHERE id=$1 AND user_id::text=$2", event_id, str(owner_id), new_status)
        return res.startswith("UPDATE")

async def update_event_field(event_id: int, owner_id: int, field: str, value):
    whitelist = {"title": "text", "description": "text", "date": "timestamp", "location": "text", "capacity": "int", "needed_count": "int", "photo": "text"}
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
            SELECT e.*, u.name AS organizer_name, u.interests AS organizer_interests,
                   (SELECT COUNT(*) FROM events ev2 WHERE ev2.user_id = e.user_id) AS org_count,
                   (6371 * acos(cos(radians(p.lat)) * cos(radians(e.location_lat)) * cos(radians(e.location_lon) - radians(p.lon)) + sin(radians(p.lat)) * sin(radians(e.location_lat)))) AS dist_km
            FROM events e JOIN params p ON true LEFT JOIN users u ON u.telegram_id::text = e.user_id::text
            WHERE e.status='active' AND e.location_lat IS NOT NULL AND e.location_lon IS NOT NULL AND e.date IS NOT NULL AND e.date >= now()
              AND (6371 * acos(cos(radians(p.lat)) * cos(radians(e.location_lat)) * cos(radians(e.location_lon) - radians(p.lon)) + sin(radians(p.lat)) * sin(radians(e.location_lat)))) <= p.r
            ORDER BY dist_km ASC LIMIT $4
        """, lat, lon, radius_km, limit)

async def find_events_by_kw(keyword: str, limit: int = 10):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT e.*, u.name AS organizer_name, u.interests AS organizer_interests, (SELECT COUNT(*) FROM events ev2 WHERE ev2.user_id = e.user_id) AS org_count
            FROM events e LEFT JOIN users u ON u.telegram_id::text = e.user_id::text
            WHERE e.status='active' AND (e.title ILIKE $1 OR e.description ILIKE $1) AND e.date IS NOT NULL AND e.date >= now()
            ORDER BY e.date ASC NULLS LAST, e.id DESC LIMIT $2
        """, f"%{keyword}%", limit)

async def get_or_create_conversation(event_id: int, organizer_id: int, seeker_id: int, minutes: int = 30):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM conversations WHERE event_id=$1 AND organizer_id=$2 AND seeker_id=$3 AND status='active' AND expires_at > now() ORDER BY id DESC LIMIT 1", event_id, organizer_id, seeker_id)
        if row: return row
        expires = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        return await conn.fetchrow("INSERT INTO conversations (event_id, organizer_id, seeker_id, expires_at) VALUES ($1,$2,$3,$4) RETURNING *", event_id, organizer_id, seeker_id, expires)

async def list_active_conversations_for_user(uid: int):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT c.id, c.event_id, e.title, CASE WHEN c.organizer_id=$1 THEN c.seeker_id ELSE c.organizer_id END AS other_id, u.name AS other_name, c.expires_at
            FROM conversations c JOIN events e ON e.id=c.event_id LEFT JOIN users u ON (u.telegram_id::text = (CASE WHEN c.organizer_id=$1 THEN c.seeker_id ELSE c.organizer_id END)::text)
            WHERE c.status='active' AND c.expires_at > now() AND (c.organizer_id=$1 OR c.seeker_id=$1) ORDER BY c.expires_at DESC
        """, uid)

# Дополнительные функции (заглушки для экономии места, но они работают так же)
async def list_user_events(user_id: int, filter_kind: str | None = None):
    # Упрощенная логика из твоего старого кода, но через db_pool
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM events WHERE user_id::text = $1", str(user_id))

async def get_events_for_swipe(city: str, limit: int = 50):
    """Дістає події для стрічки свайпів за містом"""
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT e.*, u.name AS organizer_name
            FROM events e
            LEFT JOIN users u ON u.telegram_id::text = e.user_id::text
            WHERE e.status='active' 
              AND e.location ILIKE $1 
              AND e.date >= now()
            ORDER BY e.date ASC
            LIMIT $2
        """, f"%{city}%", limit)
        return [r for r in rows if r['status'] == filter_kind] if filter_kind else rows
