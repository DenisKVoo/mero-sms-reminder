"""
Sincronizare programări mero.ro → Google Calendar (calendarul default).

Prima rulare: deschide browserul pentru autorizare Google.
Rulări ulterioare: automat, fără browser.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CREDENTIALS_FILE = Path(os.environ.get("GOOGLE_CREDENTIALS", "credentials.json"))
TOKEN_FILE = Path(os.environ.get("GOOGLE_TOKEN", "token.json"))

MERO_ID_KEY = "meroId"


def _get_service():
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Lipsește {CREDENTIALS_FILE}. "
                    "Descarcă credentials.json din Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    return build("calendar", "v3", credentials=creds)


def _find_existing_event(service, mero_id: str) -> str | None:
    """Caută un eveniment existent cu meroId în extended properties. Returnează eventId sau None."""
    result = service.events().list(
        calendarId="primary",
        privateExtendedProperty=f"{MERO_ID_KEY}={mero_id}",
        singleEvents=True,
        maxResults=1,
    ).execute()
    items = result.get("items", [])
    return items[0]["id"] if items else None


def _build_event_body(appt: dict) -> dict:
    description_parts = []
    if appt.get("phone"):
        description_parts.append(appt["phone"])

    return {
        "summary": appt["client_name"],
        "description": "\n".join(description_parts),
        "start": {
            "dateTime": appt["datetime_iso"],
            "timeZone": "Europe/Bucharest",
        },
        "end": {
            "dateTime": appt["end_iso"],
            "timeZone": "Europe/Bucharest",
        },
        "extendedProperties": {
            "private": {
                MERO_ID_KEY: appt["id"],
            }
        },
        "reminders": {"useDefault": True},
    }


def sync_to_calendar(appointments: list[dict]) -> dict:
    """
    Sincronizează lista de programări în Google Calendar.
    Returnează statistici: created, skipped, updated, errors.
    """
    service = _get_service()
    stats = {"created": 0, "skipped": 0, "errors": 0}

    for appt in appointments:
        if not appt.get("id"):
            continue
        try:
            existing_id = _find_existing_event(service, appt["id"])
            event_body = _build_event_body(appt)

            if existing_id:
                # Nu modifica evenimentele existente — userul poate adăuga notițe (ex. suma plătită)
                stats["skipped"] += 1
                print(f"  [calendar] Existent (skip): {appt['client_name']} — {appt['datetime_iso']}")
            else:
                service.events().insert(
                    calendarId="primary",
                    body=event_body,
                ).execute()
                stats["created"] += 1
                print(f"  [calendar] Adăugat: {appt['client_name']} — {appt['datetime_iso']}")

        except Exception as e:
            stats["errors"] += 1
            print(f"  [calendar] EROARE pentru {appt.get('client_name')}: {e}")

    return stats
