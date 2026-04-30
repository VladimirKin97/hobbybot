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
            try: await conn.execute("ALTER TABLE requests ADD COLUMN message TEXT;")
            except asyncpg.exceptions.DuplicateColumnError: pass
            
            # === СТАРУ ТАБЛИЦЮ RATINGS НЕ ЧІПАЄМО ДЛЯ ІСТОРІЇ, СТВОРЮЄМО НОВУ УНІВЕРСАЛЬНУ ===
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id SERIAL PRIMARY KEY, 
                event_id INT NOT NULL, 
                from_user_id BIGINT NOT NULL, 
                to_user_id BIGINT NOT NULL, 
                role_evaluated TEXT NOT NULL, 
                score INT NOT NULL, 
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(event_id, from_user_id, to_user_id)
            );
            """)
            
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id SERIAL PRIMARY KEY, reporter_id BIGINT NOT NULL, event_id INT NOT NULL,
                reason TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """)
            
            # === ДОДАЄМО СТАТИСТИКУ РЕЙТИНГІВ ПРЯМО В ТАБЛИЦЮ USERS ===
            try: 
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active TIMESTAMPTZ DEFAULT now();")
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS rating_org NUMERIC(3,2) DEFAULT 5.0;")
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS votes_org INT DEFAULT 0;")
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS rating_part NUMERIC(3,2) DEFAULT 5.0;")
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS votes_part INT DEFAULT 0;")
            except Exception as e:
                logging.error(f"Помилка оновлення колонок users: {e}")

async def get_user_from_db(user_id: int):
    async with db_pool.acquire() as conn: return await conn.fetchrow("SELECT * FROM users WHERE telegram_id::text = $1", str(user_id))

async def save_user_to_db(user_id, phone, name, city, photo, interests):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (telegram_id, phone, name, city, photo, interests, last_active) VALUES ($1,$2,$3,$4,$5,$6, now())
            ON CONFLICT (telegram_id) DO UPDATE SET phone=EXCLUDED.phone, name=EXCLUDED.name, city=EXCLUDED.city, photo=EXCLUDED.photo, interests=EXCLUDED.interests, last_active=now()
        """, user_id, phone, name, city, photo, interests)

async def update_user_activity(user_id: int):
    try:
        async with db_pool.acquire() as conn: await conn.execute("UPDATE users SET last_active = now() WHERE telegram_id::text = $1", str(user_id))
    except Exception as e: logging.error(f"Не вдалося оновити активність юзера: {e}")



# ТЕПЕР БЕРЕМО РЕЙТИНГ ПРЯМО З USERS (ДУЖЕ ШВИДКО)
async def get_organizer_avg_rating(organizer_id: int):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT rating_org FROM users WHERE telegram_id::text=$1", str(organizer_id))
        return row["rating_org"] if row else 5.0

async def find_events_near(lat: float, lon: float, radius_km: float, limit: int = 10):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            WITH params AS (SELECT $1::float AS lat, $2::float AS lon, $3::float AS r)
            SELECT e.*, u.name AS organizer_name, u.rating_org as org_rating
            FROM events e JOIN params p ON true LEFT JOIN users u ON u.telegram_id::text = e.user_id::text
            WHERE TRIM(LOWER(e.status))='active' AND e.needed_count > 0 AND e.location_lat IS NOT NULL AND e.location_lon IS NOT NULL AND e.date >= now()
              AND (6371 * acos(cos(radians(p.lat)) * cos(radians(e.location_lat)) * cos(radians(e.location_lon) - radians(p.lon)) + sin(radians(p.lat)) * sin(radians(e.location_lat)))) <= p.r
            ORDER BY (6371 * acos(cos(radians(p.lat)) * cos(radians(e.location_lat)) * cos(radians(e.location_lon) - radians(p.lon)) + sin(radians(p.lat)) * sin(radians(e.location_lat)))) ASC LIMIT $4
        """, lat, lon, radius_km, limit)

async def find_events_by_kw(keyword: str, limit: int = 10):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT e.*, u.name AS organizer_name, u.rating_org as org_rating
            FROM events e LEFT JOIN users u ON u.telegram_id::text = e.user_id::text
            WHERE TRIM(LOWER(e.status))='active' AND e.needed_count > 0 AND (e.title ILIKE $1 OR e.description ILIKE $1) AND e.date >= now()
            ORDER BY e.date ASC LIMIT $2
        """, f"%{keyword}%", limit)

async def get_events_for_swipe(city: str, limit: int = 50):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT e.*, u.name AS organizer_name, u.rating_org as org_rating
            FROM events e LEFT JOIN users u ON u.telegram_id::text = e.user_id::text
            WHERE TRIM(LOWER(e.status))='active' AND e.needed_count > 0 AND e.location ILIKE $1 AND e.date >= now()
            ORDER BY e.date ASC LIMIT $2
        """, f"%{city}%", limit)

async def list_user_events(user_id: int, filter_kind: str | None = None):
    async with db_pool.acquire() as conn:
        if filter_kind == 'active': 
            return await conn.fetch("SELECT * FROM events WHERE user_id::text = $1 AND TRIM(LOWER(status)) != 'deleted' AND date >= now() ORDER BY date ASC", str(user_id))
        return await conn.fetch("SELECT * FROM events WHERE user_id::text = $1 ORDER BY date DESC", str(user_id))

async def get_user_history(user_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT e.*, 'org' as role FROM events e WHERE e.user_id::text = $1 AND e.status != 'deleted' AND e.date < now()
            UNION ALL
            SELECT e.*, 'part' as role FROM events e JOIN requests r ON e.id = r.event_id 
            WHERE r.seeker_id::text = $1 AND r.status = 'approved' AND e.status != 'deleted' AND e.date < now()
            ORDER BY date DESC LIMIT 20
        """, str(user_id))

async def get_event_by_id(event_id: int):
    async with db_pool.acquire() as conn: 
        return await conn.fetchrow("""
            SELECT e.*, u.name AS organizer_name, u.rating_org as org_rating
            FROM events e LEFT JOIN users u ON u.telegram_id::text = e.user_id::text WHERE e.id = $1
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
    async with db_pool.acquire() as conn: return await conn.fetchrow("SELECT * FROM requests WHERE event_id = $1 AND seeker_id = $2", event_id, user_id)

async def update_request_status_db(req_id: int, status: str):
    async with db_pool.acquire() as conn: await conn.execute("UPDATE requests SET status = $1 WHERE id = $2", status, req_id)

async def decrement_needed_count(event_id: int):
    async with db_pool.acquire() as conn: 
        return await conn.fetchval("UPDATE events SET needed_count = GREATEST(needed_count - 1, 0) WHERE id = $1 RETURNING needed_count", event_id)

async def get_user_participations(user_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT e.*, r.status as req_status FROM events e JOIN requests r ON e.id = r.event_id 
            WHERE r.seeker_id::text = $1 AND r.status != 'rejected' AND r.status != 'cancelled' AND e.status != 'deleted' AND e.date >= now() ORDER BY e.date ASC
        """, str(user_id))

async def get_approved_participants(event_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT u.name, u.telegram_id FROM requests r JOIN users u ON r.seeker_id::text = u.telegram_id::text 
            WHERE r.event_id = $1 AND r.status = 'approved'
        """, event_id)

async def cancel_event_db(event_id: int):
    async with db_pool.acquire() as conn: await conn.execute("UPDATE events SET status = 'deleted' WHERE id = $1", event_id)

async def cancel_request_db(req_id: int, event_id: int, was_approved: bool):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE requests SET status = 'cancelled' WHERE id = $1", req_id)
        if was_approved: await conn.execute("UPDATE events SET needed_count = needed_count + 1 WHERE id = $1", event_id)

async def get_upcoming_reminders():
    async with db_pool.acquire() as conn: return await conn.fetch("SELECT * FROM events WHERE status='active' AND date >= now() AND date <= now() + interval '25 hours'")

async def get_past_active_events():
    async with db_pool.acquire() as conn: return await conn.fetch("SELECT * FROM events WHERE status='active' AND date < now() - interval '2 hours'")

async def mark_event_finished(event_id: int):
    async with db_pool.acquire() as conn: await conn.execute("UPDATE events SET status='finished' WHERE id=$1", event_id)

# === НОВА МАТЕМАТИКА РЕЙТИНГУ (АЛГОРИТМ ЗГЛАДЖУВАННЯ) ===
async def add_review_and_update_rating(event_id: int, from_user_id: int, to_user_id: int, role_evaluated: str, score: int):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        try:
            # 1. Записуємо або оновлюємо відгук
            await conn.execute("""
                INSERT INTO reviews (event_id, from_user_id, to_user_id, role_evaluated, score) 
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (event_id, from_user_id, to_user_id) 
                DO UPDATE SET score = EXCLUDED.score, created_at = now()
            """, event_id, from_user_id, to_user_id, role_evaluated, score)
            
            # 2. Беремо останні 50 відгуків для цієї ролі
            reviews = await conn.fetch("""
                SELECT score FROM reviews 
                WHERE to_user_id = $1 AND role_evaluated = $2 
                ORDER BY created_at DESC LIMIT 50
            """, to_user_id, role_evaluated)
            
            real_votes = len(reviews)
            if real_votes == 0: return
                
            real_sum = sum(r['score'] for r in reviews)
            
            # 3. Формула довіри (згладжування)
            if real_votes < 50:
                new_rating = (real_sum + (50 - real_votes) * 5.0) / 50.0
            else:
                new_rating = real_sum / 50.0
            
            new_rating = round(new_rating, 2)
            
            # 4. Оновлюємо статистику в users
            if role_evaluated == 'organizer':
                await conn.execute("""
                    UPDATE users SET rating_org = $1, votes_org = (SELECT COUNT(*) FROM reviews WHERE to_user_id = $2 AND role_evaluated = 'organizer') 
                    WHERE telegram_id::text = $3
                """, new_rating, to_user_id, str(to_user_id))
            else:
                await conn.execute("""
                    UPDATE users SET rating_part = $1, votes_part = (SELECT COUNT(*) FROM reviews WHERE to_user_id = $2 AND role_evaluated = 'participant') 
                    WHERE telegram_id::text = $3
                """, new_rating, to_user_id, str(to_user_id))
                
        except Exception as e:
            logging.error(f"Помилка збереження рейтингу та оновлення профілю: {e}")

async def get_admin_stats():
    async with db_pool.acquire() as conn:
        users = await conn.fetchval("SELECT COUNT(*) FROM users")
        dau = await conn.fetchval("SELECT COUNT(*) FROM users WHERE last_active >= now() - interval '24 hours'")
        wau = await conn.fetchval("SELECT COUNT(*) FROM users WHERE last_active >= now() - interval '7 days'")
        mau = await conn.fetchval("SELECT COUNT(*) FROM users WHERE last_active >= now() - interval '30 days'")
        events = await conn.fetchval("SELECT COUNT(*) FROM events WHERE status='active'")
        reqs = await conn.fetchval("SELECT COUNT(*) FROM requests")
        reports = await conn.fetchval("SELECT COUNT(*) FROM reports")
        return {"users": users, "dau": dau, "wau": wau, "mau": mau, "events": events, "requests": reqs, "reports": reports}

async def save_report_db(reporter_id: int, event_id: int, reason: str):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO reports (reporter_id, event_id, reason) VALUES ($1, $2, $3)", reporter_id, event_id, reason)
