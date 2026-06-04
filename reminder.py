"""
Script principal: verifică programările la fiecare 30 de minute și trimite
SMS-uri de reminder cu 24h și 2h înainte. Rulează non-stop pe cloud.
"""

import asyncio
import base64
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ_ROMANIA = ZoneInfo("Europe/Bucharest")


def _bootstrap_session():
    """La pornire, decodează SESSION_JSON_B64 și scrie session.json pe disk."""
    b64 = os.environ.get("SESSION_JSON_B64", "").strip()
    if not b64:
        return
    session_file = Path(os.environ.get("SESSION_FILE", "session.json"))
    if session_file.exists():
        return  # deja există, nu suprascrie
    try:
        session_file.parent.mkdir(parents=True, exist_ok=True)
        session_file.write_bytes(base64.b64decode(b64))
        print(f"[startup] session.json scris în {session_file}")
    except Exception as e:
        print(f"[startup] Eroare decodare SESSION_JSON_B64: {e}")


_bootstrap_session()

from scraper import get_appointments, fetch_appointments_direct
from sms import send_sms, build_message_24h, build_message_2h

LOG_FILE = Path(os.environ.get("LOG_FILE", "sent_sms.json"))
CHECK_INTERVAL_MINUTES = int(os.environ.get("CHECK_INTERVAL_MINUTES", "30"))
TEST_PHONE = os.environ.get("TEST_PHONE", "").strip()
ALERT_PHONE = os.environ.get("ALERT_PHONE", "").strip()
FORCE_SEND = os.environ.get("FORCE_SEND", "").lower() in ("1", "true", "yes")

# Fereastra de declanșare (în minute) în jurul momentului țintă.
# Ex: dacă programarea e la 15:00, SMS-ul de 2h se trimite oricând între 12:55-13:05.
TRIGGER_WINDOW_MINUTES = 5


def load_sent_log() -> dict:
    if LOG_FILE.exists():
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_sent_log(log: dict):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def make_key(appointment: dict, reminder_type: str) -> str:
    """Cheie unică pentru fiecare (programare, tip reminder)."""
    return f"{appointment['phone']}|{appointment['datetime_iso']}|{reminder_type}"


def should_send(target_dt: datetime, now: datetime, window_minutes: int) -> bool:
    """
    Verifică dacă suntem în fereastra de trimitere față de momentul țintă.
    Rulăm la fiecare 30 min, deci fereastra de ±5 min e suficientă.
    """
    diff = (now - target_dt).total_seconds() / 60  # minute scurse față de momentul ideal
    return -window_minutes <= diff <= window_minutes


async def process_appointments():
    if TEST_PHONE:
        print(f"\n[reminder] *** MOD TEST — toate SMS-urile merg la {TEST_PHONE} ***")
    if FORCE_SEND:
        print(f"[reminder] *** FORCE SEND — ignoră fereastra de timp, trimite imediat ***")
    print(f"\n[reminder] === Verificare la {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")

    try:
        appointments = fetch_appointments_direct()
    except PermissionError:
        print("[reminder] EROARE: Token expirat. Trebuie re-login manual.")
        if ALERT_PHONE:
            send_sms(ALERT_PHONE, "Mero SMS Reminder: sesiunea a expirat. Re-logheaza-te local si actualizeaza SESSION_JSON_B64 pe Render.")
        return
    except Exception as e:
        print(f"[reminder] Eroare la extragere programări: {e}")
        return

    print(f"[reminder] {len(appointments)} programări viitoare găsite")

    sent_log = load_sent_log()
    now = datetime.now(timezone.utc)
    new_sends = 0

    for appt in appointments:
        try:
            appt_dt = datetime.fromisoformat(appt["datetime_iso"])
            if appt_dt.tzinfo is None:
                # Dacă nu are timezone, presupunem că e ora României (UTC+3 vara, UTC+2 iarna)
                # Simplificat: tratăm ca UTC+2
                appt_dt = appt_dt.replace(tzinfo=timezone(timedelta(hours=2)))
        except (ValueError, KeyError) as e:
            print(f"[reminder] Dată invalidă pentru {appt.get('client_name')}: {e}")
            continue

        name = appt.get("client_name", "Client")
        phone = appt["phone"]
        time_str = appt_dt.astimezone(TZ_ROMANIA).strftime("%H:%M")

        # --- Reminder 24h ---
        target_24h = appt_dt - timedelta(hours=24)
        key_24h = make_key(appt, "24h")

        if key_24h not in sent_log and (FORCE_SEND or should_send(target_24h, now, TRIGGER_WINDOW_MINUTES)):
            message = build_message_24h(name, time_str)
            dest = TEST_PHONE if TEST_PHONE else phone
            print(f"[reminder] Trimit SMS 24h → {name} ({dest}): {message}")
            if send_sms(dest, message):
                sent_log[key_24h] = {
                    "sent_at": now.isoformat(),
                    "to": phone,
                    "name": name,
                    "appointment": appt["datetime_iso"],
                    "type": "24h",
                }
                new_sends += 1

        # --- Reminder 2h ---
        target_2h = appt_dt - timedelta(hours=2)
        key_2h = make_key(appt, "2h")

        if key_2h not in sent_log and (FORCE_SEND or should_send(target_2h, now, TRIGGER_WINDOW_MINUTES)):
            message = build_message_2h(name, time_str)
            dest = TEST_PHONE if TEST_PHONE else phone
            print(f"[reminder] Trimit SMS 2h → {name} ({dest}): {message}")
            if send_sms(dest, message):
                sent_log[key_2h] = {
                    "sent_at": now.isoformat(),
                    "to": phone,
                    "name": name,
                    "appointment": appt["datetime_iso"],
                    "type": "2h",
                }
                new_sends += 1

    if new_sends > 0:
        save_sent_log(sent_log)
        print(f"[reminder] {new_sends} SMS-uri trimise. Log salvat.")
    else:
        print("[reminder] Niciun SMS de trimis acum.")


async def cleanup_old_log_entries(sent_log: dict) -> dict:
    """Șterge intrările mai vechi de 30 de zile pentru a nu crește log-ul la infinit."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    return {
        k: v for k, v in sent_log.items()
        if datetime.fromisoformat(v["sent_at"]) > cutoff
    }


async def main():
    print("[reminder] Pornit. Verificare la fiecare "
          f"{CHECK_INTERVAL_MINUTES} minute.")

    while True:
        await process_appointments()

        # Curăță log-ul o dată pe zi (la prima rulare din zi)
        if datetime.now().hour == 3:
            log = load_sent_log()
            cleaned = await cleanup_old_log_entries(log)
            if len(cleaned) < len(log):
                save_sent_log(cleaned)
                print(f"[reminder] Log curățat: {len(log) - len(cleaned)} intrări vechi șterse.")

        await asyncio.sleep(CHECK_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    asyncio.run(main())
