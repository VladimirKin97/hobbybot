import re
from datetime import datetime, timezone

def _now_utc() -> datetime:
    """Повертає поточний час в UTC"""
    return datetime.now(timezone.utc)

MONTHS = {
    "січня":1,"лютого":2,"березня":3,"квітня":4,"травня":5,"червня":6,
    "липня":7,"серпня":8,"вересня":9,"жовтня":10,"листопада":11,"грудня":12,
    "января":1,"февраля":2,"марта":3,"апреля":4,"мая":5,"июня":6,
    "июля":7,"августа":8,"сентября":9,"октября":10,"ноября":11,"декабря":12,
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
}

def parse_user_datetime(text: str) -> datetime | None:
    """Парсить дату та час, введені користувачем"""
    s = text.strip().lower()
    
    # Формат 10.10.2025 19:30
    m = re.match(r"^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\s+(\d{1,2}):(\d{2})$", s)
    if m:
        dd, mm, yyyy, HH, MM = map(int, m.groups())
        return datetime(yyyy, mm, dd, HH, MM)
        
    # Формат 2025-10-10 19:30
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})$", s)
    if m:
        yyyy, mm, dd, HH, MM = map(int, m.groups())
        return datetime(yyyy, mm, dd, HH, MM)
        
    # Формат 10 жовтня 2025 19:30
    m = re.match(r"^(\d{1,2})\s+([a-zа-яіїєё]+)\s+(\d{4})\s+(\d{1,2}):(\d{2})$", s, re.IGNORECASE)
    if m:
        dd = int(m.group(1))
        mon = m.group(2)
        yyyy = int(m.group(3))
        HH = int(m.group(4))
        MM = int(m.group(5))
        mm = MONTHS.get(mon)
        if mm:
            return datetime(yyyy, mm, dd, HH, MM)
            
    return None

def parse_time_hhmm(s: str) -> tuple[int,int] | None:
    """Парсить лише час HH:MM"""
    m = re.match(r"^(\d{1,2})[:.](\d{2})$", s.strip())
    if not m: return None
    HH, MM = map(int, m.groups())
    if 0 <= HH <= 23 and 0 <= MM <= 59: return HH, MM
    return None

def tg_link_from_username(username: str | None) -> str:
    """Робить клікабельне посилання на юзернейм"""
    if username:
        u = username.lstrip("@")
        return f'<a href="https://t.me/{u}">@{u}</a>'
    return "нікнейм відсутній"
