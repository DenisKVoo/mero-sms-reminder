"""
Extrage programările viitoare din pro.mero.ro.
Calea principală: request direct API cu Bearer token din session.json (rapid, fără browser).
Fallback: Playwright cu login manual dacă tokenul a expirat.
"""

import asyncio
import json
import os
import re
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, Response, BrowserContext

SESSION_FILE = Path(os.environ.get("SESSION_FILE", "session.json"))
SIGN_IN_URL = "https://pro.mero.ro/sign-in"
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

    resp = requests.get(url, headers=headers, params=params, timeout=15)
    print(f"[scraper] API {date.strftime('%Y-%m-%d')}: HTTP {resp.status_code}")

    if resp.status_code == 401:
        raise PermissionError("Token expirat")
    resp.raise_for_status()

    return resp.json().get("calendars", [])


def _parse_calendars(calendars: list, now: datetime) -> list[dict]:
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
            if not phone:
                continue
            datetime_iso = entry.get("start", "")
            if not datetime_iso:
                continue
            try:
                appt_dt = datetime.fromisoformat(datetime_iso.replace("Z", "+00:00"))
                if appt_dt <= now:
                    continue
            except ValueError:
                pass
            name = f"{client.get('firstname', '')} {client.get('lastname', '')}".strip() or "Client"
            appointments.append({
                "client_name": name,
                "phone": _normalize_phone(phone),
                "datetime_iso": datetime_iso,
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


# ── Fallback Playwright (doar la prima rulare sau token expirat) ─────────────

class _PlaywrightScraper:
    def __init__(self):
        self._api_responses: list[dict] = []
        self._all_json_urls: list[str] = []

    async def _handle_response(self, response: Response):
        url = response.url
        if response.status == 200:
            try:
                if "json" in response.headers.get("content-type", ""):
                    data = await response.json()
                    self._all_json_urls.append(url)
                    if any(kw in url for kw in ["appointment", "booking", "reservation", "calendar", "schedule"]):
                        self._api_responses.append({"url": url, "data": data})
            except Exception:
                pass

    async def fetch(self) -> list[dict]:
        async with async_playwright() as p:
            user_agent = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
            storage_state = SESSION_FILE if SESSION_FILE.exists() else None

            # Încearcă headless cu sesiunea existentă
            if storage_state:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    storage_state=str(storage_state), user_agent=user_agent
                )
                page = await context.new_page()
                await page.goto(CALENDAR_URL, wait_until="load")
                await page.wait_for_timeout(2000)
                logged_in = "sign-in" not in page.url and "login" not in page.url
                await page.close()

                if logged_in:
                    page = await context.new_page()
                    page.on("response", self._handle_response)
                    await page.goto(CALENDAR_URL, wait_until="load")
                    await page.wait_for_timeout(3000)
                    await context.storage_state(path=str(SESSION_FILE))
                    appointments = self._parse_api_responses()
                    await browser.close()
                    return appointments
                await browser.close()
                print("[scraper] Sesiune expirată. Deschid browserul pentru re-login...")

            # Login manual
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(user_agent=user_agent)
            page = await context.new_page()
            await page.goto(SIGN_IN_URL, wait_until="domcontentloaded")

            print("\n" + "=" * 55)
            print("  Browserul s-a deschis pe pagina de login.")
            print("  Loghează-te cu Google sau număr de telefon.")
            print("  Când ești logat și VEZI CALENDARUL,")
            print("  apasă ENTER aici în terminal.")
            print("=" * 55 + "\n")

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, input, "Apasă ENTER după ce ești logat: ")

            current_url = page.url
            if "sign-in" in current_url or "login" in current_url:
                print(f"[scraper] EROARE: Încă pe pagina de login. Încearcă din nou.")
                await browser.close()
                return []

            print(f"[scraper] Login confirmat.")
            await context.storage_state(path=str(SESSION_FILE))
            print(f"[scraper] Sesiune salvată în {SESSION_FILE}")

            page.on("response", self._handle_response)
            await page.reload(wait_until="load")
            await page.wait_for_timeout(3000)

            appointments = self._parse_api_responses()
            await browser.close()
            return appointments

    def _parse_api_responses(self) -> list[dict]:
        now = datetime.now(timezone.utc)
        appointments = []
        for resp in self._api_responses:
            if "calendars-entries" not in resp["url"]:
                continue
            appointments.extend(_parse_calendars(resp["data"].get("calendars", []), now))
        return appointments


async def _fetch_appointments_playwright() -> list[dict]:
    return await _PlaywrightScraper().fetch()


# ── Punct de intrare principal ───────────────────────────────────────────────

async def get_appointments() -> list[dict]:
    """
    Încearcă mai întâi request direct API (rapid).
    Dacă tokenul e expirat, face fallback la Playwright cu login manual.
    """
    try:
        appointments = fetch_appointments_direct()
        print(f"[scraper] Request direct API OK — {len(appointments)} programări.")
        return appointments
    except PermissionError:
        print("[scraper] Token expirat — fallback la Playwright cu login manual.")
    except FileNotFoundError:
        print("[scraper] Nicio sesiune salvată — pornesc Playwright pentru login.")
    except Exception as e:
        print(f"[scraper] Eroare request direct ({e}) — fallback la Playwright.")

    return await _fetch_appointments_playwright()


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
        print(f"\n{len(appts)} programări găsite (direct API):")
        print(json.dumps(appts, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"[scraper] Direct API eșuat ({e}), încerc Playwright...")
        appts = asyncio.run(_fetch_appointments_playwright())
        print(f"\n{len(appts)} programări găsite (Playwright):")
        print(json.dumps(appts, indent=2, ensure_ascii=False))
