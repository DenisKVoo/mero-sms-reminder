import sys
import os
import base64
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def _bootstrap_files():
    mapping = {
        "GOOGLE_TOKEN_B64": os.environ.get("GOOGLE_TOKEN", "token.json"),
        "GOOGLE_CREDS_B64": os.environ.get("GOOGLE_CREDENTIALS", "credentials.json"),
        "SESSION_JSON_B64": os.environ.get("SESSION_FILE", "session.json"),
    }
    for env_var, filename in mapping.items():
        data = os.environ.get(env_var, "").strip()
        if data and not os.path.exists(filename):
            with open(filename, "wb") as f:
                f.write(base64.b64decode(data))
            print(f"[startup] {filename} scris din {env_var}")


_bootstrap_files()

from scraper import fetch_appointments_calendar
from calendar_sync import sync_to_calendar

DAYS_AHEAD = 30


def main():
    print(f"[sync] Preiau programarile din mero.ro (urmatoarele {DAYS_AHEAD} zile)...")
    try:
        appointments = fetch_appointments_calendar(days=DAYS_AHEAD)
    except FileNotFoundError as e:
        print(f"[sync] EROARE: {e}")
        sys.exit(1)
    except PermissionError:
        print("[sync] EROARE: Token mero.ro expirat.")
        sys.exit(1)

    print(f"[sync] {len(appointments)} programari gasite.")
    if not appointments:
        print("[sync] Nimic de sincronizat.")
        return

    print("[sync] Sincronizez cu Google Calendar...")
    stats = sync_to_calendar(appointments)
    print(f"\n[sync] Gata! Adaugate: {stats['created']} | Existente: {stats['skipped']} | Erori: {stats['errors']}")


if __name__ == "__main__":
    main()
