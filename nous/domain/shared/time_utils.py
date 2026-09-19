from __future__ import annotations

import math
import re
import secrets
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

_DEFAULT_TZ = "Asia/Tokyo"

# Recency decay の減衰率（exp(-λ * days)、半減期 ≈ 1.4 日）。
# 旧所在地: nous/application/chat/pipeline/emotion_decay.py（re-export に置換）。
RECENCY_LAMBDA = 0.5


def compute_recency_decay(created_at: datetime | None) -> float:
    """Compute recency decay: exp(-λ * days_elapsed) with λ=0.5.

    ``None`` は安全側の 0.5 を返す。naive datetime は UTC とみなして補完する。
    """
    if created_at is None:
        return 0.5
    now = datetime.now(tz=UTC)
    # Ensure tz-aware comparison
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    days_elapsed = max(0.0, (now - created_at).total_seconds() / 86400.0)
    return math.exp(-RECENCY_LAMBDA * days_elapsed)


def get_now(tz: str = _DEFAULT_TZ) -> datetime:
    """Return current time in the given timezone."""
    return datetime.now(ZoneInfo(tz))


def format_iso(dt: datetime) -> str:
    """Format datetime as ISO 8601 string with timezone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(_DEFAULT_TZ))
    return dt.isoformat()


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 datetime string."""
    return datetime.fromisoformat(s)


def generate_memory_key(prefix: str = "memory") -> str:
    """Generate a timestamped memory key: {prefix}_YYYYMMDDHHMMSS_microseconds_random."""
    now = get_now()
    random_suffix = secrets.token_hex(4)
    return f"{prefix}_{now.strftime('%Y%m%d%H%M%S')}_{now.microsecond:06d}_{random_suffix}"


def relative_time_str(dt: datetime, now: datetime | None = None) -> str:
    """Return a relative time string (e.g. '2h ago', '3d ago')."""
    if now is None:
        now = get_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(_DEFAULT_TZ))
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo(_DEFAULT_TZ))

    diff = now - dt
    seconds = int(diff.total_seconds())

    if seconds < 0:
        return "in the future"
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h ago"
    if seconds < 2592000:
        days = seconds // 86400
        return f"{days}d ago"
    if seconds < 31536000:
        months = seconds // 2592000
        return f"{months}mo ago"
    years = seconds // 31536000
    return f"{years}y ago"


def _kanji_to_int(text: str) -> int | None:
    """Convert kanji number string to int. Supports 一〜九百九十九."""
    kanji_digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

    if not text:
        return None

    # Try Arabic numeral first
    try:
        return int(text)
    except ValueError:
        pass

    # Simple kanji: single digit
    if text in kanji_digits:
        return kanji_digits[text]

    # Handle 十, 百
    result = 0
    current = 0
    for ch in text:
        if ch in kanji_digits:
            current = kanji_digits[ch]
        elif ch == "十":
            result += (current or 1) * 10
            current = 0
        elif ch == "百":
            result += (current or 1) * 100
            current = 0
    result += current
    return result if result > 0 else None


def parse_date_range(date_range: str | None) -> tuple[datetime | None, datetime | None]:
    """Parse date range string into (start, end) datetimes.

    Supports:
      - Japanese: 昨日, 一昨日, おととい, 今日, 先週, 先月, 今朝, 今晩, 今夜
      - N日前, N週間前, Nヶ月前, Nか月前 (kanji + arabic numbers)
      - Relative: 7d, 30d
      - Absolute: 2025-01-01~2025-06-01
    """
    if not date_range:
        return None, None

    text = date_range.strip()
    now = get_now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    # Exact Japanese expressions
    if text == "昨日":
        yesterday = today_start - timedelta(days=1)
        return yesterday, yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)

    if text in ("一昨日", "おととい"):
        day = today_start - timedelta(days=2)
        return day, day.replace(hour=23, minute=59, second=59, microsecond=999999)

    if text == "今日":
        return today_start, now

    if text == "先週":
        # Last week Monday to Sunday
        days_since_monday = now.weekday()
        this_monday = today_start - timedelta(days=days_since_monday)
        last_monday = this_monday - timedelta(weeks=1)
        last_sunday = this_monday - timedelta(seconds=1)
        return last_monday, last_sunday

    if text == "先月":
        # First day of last month to last day of last month
        first_of_this_month = today_start.replace(day=1)
        last_day_of_prev = first_of_this_month - timedelta(days=1)
        first_of_prev = last_day_of_prev.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return first_of_prev, last_day_of_prev.replace(hour=23, minute=59, second=59, microsecond=999999)

    if text == "今朝":
        return today_start, today_start.replace(hour=12)

    if text in ("今晩", "今夜"):
        return today_start.replace(hour=18), today_end

    # N日前 pattern (kanji or arabic)
    m = re.match(r"^([一二三四五六七八九十百\d]+)日前$", text)
    if m:
        n = _kanji_to_int(m.group(1))
        if n is not None:
            day = today_start - timedelta(days=n)
            return day, day.replace(hour=23, minute=59, second=59, microsecond=999999)

    # N週間前 pattern
    m = re.match(r"^([一二三四五六七八九十百\d]+)週間前$", text)
    if m:
        n = _kanji_to_int(m.group(1))
        if n is not None:
            end = today_start - timedelta(weeks=n - 1)
            start = end - timedelta(weeks=1)
            return start, end.replace(hour=23, minute=59, second=59, microsecond=999999)

    # Nヶ月前 / Nか月前 pattern
    m = re.match(r"^([一二三四五六七八九十百\d]+)[ヶか]月前$", text)
    if m:
        n = _kanji_to_int(m.group(1))
        if n is not None:
            year = now.year
            month = now.month - n
            while month <= 0:
                month += 12
                year -= 1
            first_of_target = today_start.replace(year=year, month=month, day=1)
            if month == 12:
                last_of_target = today_start.replace(year=year + 1, month=1, day=1) - timedelta(days=1)
            else:
                last_of_target = today_start.replace(year=year, month=month + 1, day=1) - timedelta(days=1)
            return first_of_target, last_of_target.replace(hour=23, minute=59, second=59, microsecond=999999)

    # Relative days: 7d, 30d
    m = re.match(r"^(\d+)d$", text)
    if m:
        days = int(m.group(1))
        return now - timedelta(days=days), now

    # Absolute range: YYYY-MM-DD~YYYY-MM-DD
    if "~" in text:
        parts = text.split("~", 1)
        try:
            start = parse_iso(parts[0].strip())
            end = parse_iso(parts[1].strip())
            if start and end:
                return start, end
        except Exception:
            pass

    return None, None
