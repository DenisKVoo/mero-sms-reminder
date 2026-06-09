"""
Extrage programările viitoare din pro.mero.ro.
Calea principală: request direct API cu Bearer token din session.json (rapid, fără browser).
"""

import asyncio
import json
import os
import re
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

SESSION_FILE = Path(os.environ.get("SESSION_FILE", "session.json"))
CALENDAR_URL = "https://pro.mero.ro/calendar"
API_BASE = "https://pro.mero.ro/api/v2.0"

# Date fixe din sesiunea salvată
PAGE_ID = "677263978267c98933701e03"
CALENDAR_IDS = [
    "678e68d6e5e9c8281a3f4148",
    "677263978267c97f4c701e09",
    "678e6b22e5e9c8b84a3fb27b",
    "6936f99277b73ac9c6a230ac",
    "69afa93986e1d659161afecc",
]


def _load_token() -> Optional[str]:
    """Citește Bearer token-ul din session.json."""
    if not SESSION_FILE.exists():
        return None
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        for origin in data.get("origins", []):
            for item in origin.get("localStorage", []):
                if item.get("name") == "authGrant":
                    grant = json.loads(item["value"])
                    return grant.get("accessToken")
    except Exception as e:
        print(f"[scraper] Eroare citire token: {e}")
    return None


def _fetch_day_direct(token: str, date: datetime) -> list[dict]:
    """Fetch programări pentru o zi prin request direct API."""
    from_dt = date.replace(hour=0, minute=0, second=0, microsecond=0)
    to_dt = date.replace(hour=23, minute=59, second=59, microsecond=999000)

    params = {
        "from": from_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "to": to_dt.strftime("%Y-%m-%dT%H:%M:%S.999Z"),
    }
    for cid in CALENDAR_IDS:
        params.setdefault("calendarIds[]", [])
        if isinstance(params["calendarIds[]"], list):
            params["calendarIds[]"].append(cid)
        else:
            params["calendarIds[]"] = [params["calendarIds[]"], cid]

    url = f"{API_BASE}/calendar/page/{PAGE_ID}/management/calendars-entries"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://pro.mero.ro/calendar",
    }

    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            print(f"[scraper] API {date.strftime('%Y-%m-%d')}: HTTP {resp.status_code}")
            if resp.status_code == 401:
                raise PermissionError("Token expirat")
            resp.raise_for_status()
            return resp.json().get("calendars", [])
        except PermissionError:
            raise
        except Exception as e:
            if attempt < 2:
                print(f"[scraper] Retry {attempt + 1}/3 pentru {date.strftime('%Y-%m-%d')}: {e}")
                import time; time.sleep(3)
            else:
                raise


def _parse_calendars(calendars: list, now: datetime, include_past: bool = False) -> list[dict]:
    """Extrage programările Denis Tanase din răspunsul API."""
    appointments = []
    for calendar in calendars:
        for entry in calendar.get("entries", []):
            if entry.get("type") != 0:
                continue
            payload = entry.get("payload", {})
            if payload.get("status") != 1:
                continue
            worker = payload.get("worker", {})
            if worker.get("firstname") != "Denis" or worker.get("lastname") != "Tanase":
                continue
            client = payload.get("client", {})
            phone = client.get("phone", "")
            start_iso = entry.get("start", "")
            if not start_iso:
                continue
            if not include_past:
                try:
                    appt_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
                    if appt_dt <= now:
                        continue
                except ValueError:
                    pass
            name = f"{client.get('firstname', '')} {client.get('lastname', '')}".strip() or "Client"
            services = ", ".join(
                s.get("name", "") for s in payload.get("bookedServices", []) if s.get("name")
            )
            appointments.append({
                "id": entry.get("_id", ""),
                "client_name": name,
                "phone": _normalize_phone(phone) if phone else "",
                "datetime_iso": start_iso,
                "end_iso": entry.get("end", ""),
                "services": services,
            })
    return appointments


def fetch_appointments_direct() -> list[dict]:
    """
    Calea rapidă: request direct API cu Bearer token.
    Returnează programările de azi și mâine.
    Ridică PermissionError dacă tokenul e expirat.
    """
    token = _load_token()
    if not token:
        raise FileNotFoundError("Nu există session.json sau token lipsă")

    now = datetime.now(timezone.utc)
    today = now
    tomorrow = now + timedelta(days=1)

    appointments = []
    for day in [today, tomorrow]:
        calendars = _fetch_day_direct(token, day)
        appointments.extend(_parse_calendars(calendars, now))

    return appointments


def fetch_appointments_calendar(days: int = 30) -> list[dict]:
    """
    Fetch programări pentru următoarele `days` zile (pentru Google Calendar sync).
    Include și programările de azi, inclusiv cele deja trecute.
    """
    token = _load_token()
    if not token:
        raise FileNotFoundError("Nu există session.json sau token lipsă")

    now = datetime.now(timezone.utc)
    appointments = []
    seen_ids: set[str] = set()

    for i in range(days):
        day = now + timedelta(days=i)
        calendars = _fetch_day_direct(token, day)
        for appt in _parse_calendars(calendars, now, include_past=True):
            if appt["id"] and appt["id"] not in seen_ids:
                seen_ids.add(appt["id"])
                appointments.append(appt)

    return appointments


async def get_appointments() -> list[dict]:
    """Returnează programările de azi și mâine."""
    try:
        appointments = fetch_appointments_direct()
        print(f"[scraper] Request direct API OK — {len(appointments)} programări.")
        return appointments
    except PermissionError:
        print("[scraper] Token expirat.")
    except FileNotFoundError:
        print("[scraper] Nicio sesiune salvată.")
    except Exception as e:
        print(f"[scraper] Eroare: {e}")
    return []


def _normalize_phone(phone: str) -> str:
    digits = re.sub(r'\D', '', str(phone))
    if digits.startswith("40") and len(digits) == 11:
        return f"+{digits}"
    if digits.startswith("0") and len(digits) == 10:
        return f"+4{digits}"
    if digits.startswith("7") and len(digits) == 9:
        return f"+40{digits}"
    return f"+{digits}"


if __name__ == "__main__":
    try:
        print("[scraper] Încerc request direct API...")
        appts = fetch_appointments_direct()
        print(f"\n{len(appts)} programări găsite:")
        print(json.dumps(appts, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"[scraper] Eroare: {e}")
