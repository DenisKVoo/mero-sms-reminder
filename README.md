# Mero → Google Calendar Sync

Automatizare care sincronizează programările din [mero.ro](https://pro.mero.ro) direct în Google Calendar, rulând 24/7 fără intervenție manuală.

## Ce face

- ✅ **Adaugă automat** programările noi din mero.ro în Google Calendar
- ✅ **Șterge automat** programările anulate din mero.ro din Google Calendar
- ✅ **Păstrează notițele** adăugate manual în Calendar (nu suprascrie evenimentele existente)
- ✅ **Rulează la fiecare 15 minute** via cron-job.org + GitHub Actions
- ✅ **100% gratuit**, fără server propriu, fără laptop pornit

## Arhitectură

```
cron-job.org (15 min) → GitHub Actions → scraper.py → Google Calendar API
```

1. **cron-job.org** trimite un request HTTP la GitHub la fiecare 15 minute
2. **GitHub Actions** pornește workflow-ul
3. **scraper.py** extrage programările din API-ul mero.ro (Bearer token)
4. **calendar_sync.py** sincronizează cu Google Calendar (adaugă noi / șterge anulate)

## Tehnologii

- **Python 3.11**
- **Google Calendar API** (OAuth2)
- **GitHub Actions** (CI/CD + scheduling)
- **cron-job.org** (trigger extern fiabil)
- **mero.ro API** (request direct cu Bearer token)

## Setup

### 1. Credențiale Google Calendar
- Creează un proiect în [Google Cloud Console](https://console.cloud.google.com)
- Activează Google Calendar API
- Descarcă `credentials.json` (OAuth2 Desktop App)
- Rulează local o dată pentru a genera `token.json`

### 2. Secretele GitHub
Encodează fișierele în base64 și adaugă-le ca GitHub Secrets:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("token.json"))
[Convert]::ToBase64String([IO.File]::ReadAllBytes("credentials.json"))
[Convert]::ToBase64String([IO.File]::ReadAllBytes("session.json"))
```

Secrets necesare:
- `GOOGLE_TOKEN_B64`
- `GOOGLE_CREDS_B64`
- `SESSION_JSON_B64`

### 3. cron-job.org
Creează un job pe [cron-job.org](https://cron-job.org) cu:
- **URL:** `https://api.github.com/repos/USER/REPO/dispatches`
- **Method:** POST
- **Headers:** `Authorization: Bearer <github-token>`, `Content-Type: application/json`
- **Body:** `{"event_type": "force-sync"}`
- **Interval:** 15 minute

### 4. session.json
Loghează-te pe pro.mero.ro → F12 → Application → Local Storage → copiază `authGrant` → salvează în `session.json`.

## Structura proiect

```
├── scraper.py          # Extrage programările din mero.ro API
├── calendar_sync.py    # Sincronizare cu Google Calendar
├── sync_calendar.py    # Script principal
├── requirements.txt    # Dependențe Python
└── .github/
    └── workflows/
        └── sync.yml    # GitHub Actions workflow
```

## Notă

Tokenul mero.ro expiră periodic. La expirare, re-loghează-te pe pro.mero.ro, salvează noua sesiune și actualizează secretul `SESSION_JSON_B64` pe GitHub.
