"""
Trimitere SMS via SMS Gateway for Android (github.com/capcom6/android-sms-gateway).
Gratuit — SMS-urile pleacă de pe numărul tău personal de telefon.
"""

import os
import httpx

# Credențiale generate de aplicația Android (Settings → Cloud)
SMS_GW_USER = os.environ["SMS_GW_USER"]
SMS_GW_PASS = os.environ["SMS_GW_PASS"]
SALON_PHONE = os.environ["SALON_PHONE"]   # ex: 0722123456
SENDER_NAME = os.environ.get("SENDER_NAME", "Salon")  # doar pentru referință locală

# Cloud relay — funcționează indiferent unde e telefonul (acasă, în salon etc.)
CLOUD_API_URL = "https://api.sms-gate.app/3rdparty/v1/message"


def send_sms(to_phone: str, message: str) -> bool:
    """
    Trimite un SMS prin aplicația Android.
    Returnează True dacă request-ul a fost acceptat, False altfel.
    """
    payload = {
        "message": message,
        "phoneNumbers": [to_phone],
    }

    try:
        resp = httpx.post(
            CLOUD_API_URL,
            json=payload,
            auth=(SMS_GW_USER, SMS_GW_PASS),
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()

        # API returnează fie un dict cu 'state', fie o listă de dict-uri
        if isinstance(result, list):
            state = result[0].get("state", "") if result else ""
        else:
            state = result.get("state", "")

        if state in ("Pending", "Processed", "Sent"):
            print(f"[sms] Trimis către {to_phone} (state: {state})")
            return True

        print(f"[sms] Stare necunoscută pentru {to_phone}: {state} — {result}")
        return True

    except httpx.HTTPStatusError as e:
        print(f"[sms] Eroare HTTP {e.response.status_code} pentru {to_phone}: {e.response.text}")
        return False
    except Exception as e:
        print(f"[sms] Excepție la trimitere SMS către {to_phone}: {e}")
        return False


def build_message_24h(client_name: str, time_str: str) -> str:
    first_name = client_name.split()[0] if client_name else "drag"
    return (
        f"Salut {first_name}. Iti amintesc de programarea de la ora {time_str} de maine. "
        f"Pentru modificari suna la {SALON_PHONE}."
    )


def build_message_2h(client_name: str, time_str: str) -> str:
    first_name = client_name.split()[0] if client_name else "drag"
    return (
        f"Salut {first_name}. Iti amintesc de programarea de la ora {time_str} de azi. "
        f"Pentru modificari suna la {SALON_PHONE}."
    )
