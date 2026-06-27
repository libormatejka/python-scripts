import os
import time
import json
import requests
import webbrowser
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode

import gspread
from google.oauth2.service_account import Credentials

# ── Konfigurace ───────────────────────────────────────────────────────────────

CLIENT_ID       = os.environ.get("STRAVA_CLIENT_ID", "")
CLIENT_SECRET   = os.environ.get("STRAVA_CLIENT_SECRET", "")
TOKEN_FILE      = os.environ.get("STRAVA_TOKEN_FILE", ".strava_token.json")
# Nastav při prvním spuštění lokálně, pak zkopíruj do GitHub secret STRAVA_REFRESH_TOKEN
REFRESH_TOKEN_ENV = os.environ.get("STRAVA_REFRESH_TOKEN", "")

# Cesta k Service Account JSON klíči (stáhnout z Google Cloud Console)
GOOGLE_CREDS    = os.environ.get("GOOGLE_CREDENTIALS_FILE", "google_credentials.json")
SPREADSHEET_ID  = "1MxnYvXjVUorTTe05UV-OxBV-LwZmSBMtXtwL8YFS6k8"
SHEET_NAME      = "Data-python"

REDIRECT_URI    = "http://localhost:8765/callback"
AUTH_URL        = "https://www.strava.com/oauth/authorize"
TOKEN_URL       = "https://www.strava.com/oauth/token"
API_BASE        = "https://www.strava.com/api/v3"
SCOPES          = "activity:read_all"

COLUMNS = [
    "id", "date", "name", "type", "distance (meters)", "kudos",
    "elev_low", "elev_high", "average_heartrate", "max_heartrate",
    "moving_time", "elapsed_time (seconds)", "calories", "elevation",
    "total_elevation_gain", "pace", "average_speed", "max_speed", "workout_type",
]

# ── Token management ──────────────────────────────────────────────────────────

def save_token(token: dict):
    with open(TOKEN_FILE, "w") as f:
        json.dump(token, f, indent=2)

def load_token() -> dict | None:
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE) as f:
        content = f.read().strip()
    if not content:
        return None
    return json.loads(content)

def refresh_token(token: dict) -> dict:
    resp = requests.post(TOKEN_URL, data={
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type":    "refresh_token",
        "refresh_token": token["refresh_token"],
    })
    resp.raise_for_status()
    new_token = resp.json()
    save_token(new_token)
    print("Token obnoven.")
    return new_token

def get_valid_token() -> dict:
    # Priorita 1: token soubor (lokální spuštění nebo předchozí refresh)
    token = load_token()
    if token:
        if token.get("expires_at", 0) - time.time() < 60:
            token = refresh_token(token)
        return token

    # Priorita 2: refresh token z env proměnné (GitHub Actions)
    if REFRESH_TOKEN_ENV:
        print("Používám STRAVA_REFRESH_TOKEN z env proměnné...")
        synthetic = {"refresh_token": REFRESH_TOKEN_ENV, "expires_at": 0}
        return refresh_token(synthetic)

    # Priorita 3: browser OAuth flow (první lokální spuštění)
    return oauth_flow()

# ── OAuth2 flow ───────────────────────────────────────────────────────────────

_auth_code: str | None = None

class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        params = parse_qs(urlparse(self.path).query)
        _auth_code = params.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("<h2>Autorizace proběhla. Můžete zavřít tento tab.</h2>".encode())

    def log_message(self, *args):
        pass

def exchange_code(code: str) -> dict:
    resp = requests.post(TOKEN_URL, data={
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code":          code,
        "grant_type":    "authorization_code",
    })
    resp.raise_for_status()
    token = resp.json()
    save_token(token)
    print("Token uložen.")
    return token

def oauth_flow() -> dict:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError(
            "Nastav STRAVA_CLIENT_ID a STRAVA_CLIENT_SECRET jako env proměnné.\n"
            "Aplikaci vytvoříš na https://www.strava.com/settings/api"
        )

    # Ruční zadání kódu přes env (když callback nedorazí)
    manual_code = os.environ.get("STRAVA_AUTH_CODE", "").strip()
    if manual_code:
        print("Používám STRAVA_AUTH_CODE z env proměnné...")
        return exchange_code(manual_code)

    params = {
        "client_id":       CLIENT_ID,
        "redirect_uri":    REDIRECT_URI,
        "response_type":   "code",
        "approval_prompt": "auto",
        "scope":           SCOPES,
    }
    url = f"{AUTH_URL}?{urlencode(params)}"
    print("\n" + "="*60)
    print("OTEVRI TUTO URL V PROHLIZECI:")
    print(url)
    print("="*60 + "\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    server = HTTPServer(("0.0.0.0", 8765), _CallbackHandler)
    print("Cekam na callback (port 8765)...")
    server.handle_request()
    server.server_close()

    if not _auth_code:
        raise RuntimeError("Autorizační kód nebyl přijat.")

    return exchange_code(_auth_code)

# ── Strava API ────────────────────────────────────────────────────────────────

def api_get(endpoint: str, token: dict, params: dict = None) -> dict | list:
    headers = {"Authorization": f"Bearer {token['access_token']}"}
    resp = requests.get(f"{API_BASE}{endpoint}", headers=headers, params=params or {})
    if resp.status_code == 429:
        reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 900))
        wait  = max(reset - int(time.time()), 60)
        print(f"Rate limit — čekám {wait}s...")
        time.sleep(wait)
        return api_get(endpoint, token, params)
    resp.raise_for_status()
    return resp.json()

def fetch_all_activities(token: dict) -> list[dict]:
    activities = []
    page = 1
    print("Stahuji aktivity ze Strava...")
    while True:
        batch = api_get("/athlete/activities", token, {"per_page": 100, "page": page})
        if not batch:
            break
        activities.extend(batch)
        print(f"  stránka {page}: {len(batch)} aktivit (celkem {len(activities)})")
        page += 1
        time.sleep(0.4)
    return activities

def fetch_detail(token: dict, activity_id: int) -> dict:
    return api_get(f"/activities/{activity_id}", token)

# ── Transformace ──────────────────────────────────────────────────────────────

def format_pace(moving_time_s: float | None, distance_m: float | None) -> str:
    if not moving_time_s or not distance_m or distance_m == 0:
        return ""
    return round(moving_time_s / (distance_m / 1000))

def format_moving_time(seconds: int | None) -> str:
    """Vrátí moving_time ve formátu hh:mm:ss."""
    if seconds is None:
        return ""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02d}:{s:02d}"

def activity_to_row(act: dict) -> list:
    distance  = act.get("distance")
    moving    = act.get("moving_time")
    avg_speed = act.get("average_speed")
    max_speed = act.get("max_speed")

    # date: ISO → lokální datum
    raw_date = act.get("start_date_local", "")
    date_str = raw_date[:10] if raw_date else ""

    return [
        act.get("id", ""),
        date_str,
        act.get("name", ""),
        act.get("sport_type") or act.get("type", ""),
        round(distance, 1) if distance is not None else "",
        act.get("kudos_count", ""),
        act.get("elev_low", ""),
        act.get("elev_high", ""),
        act.get("average_heartrate", ""),
        act.get("max_heartrate", ""),
        format_moving_time(moving),
        act.get("elapsed_time", ""),
        act.get("calories", ""),
        act.get("elev_high", ""),           # "elevation" — nejvyšší bod trasy
        act.get("total_elevation_gain", ""),
        format_pace(moving, distance),
        round(avg_speed * 3.6, 2) if avg_speed is not None else "",   # m/s → km/h
        round(max_speed * 3.6, 2) if max_speed is not None else "",   # m/s → km/h
        act.get("workout_type", ""),
    ]

# ── Google Sheets ─────────────────────────────────────────────────────────────

def open_sheet():
    if not os.path.exists(GOOGLE_CREDS):
        raise FileNotFoundError(
            f"Soubor s Google credentials nebyl nalezen: {GOOGLE_CREDS}\n"
            "Stáhni Service Account JSON z Google Cloud Console a ulož ho,\n"
            "nebo nastav cestu přes env proměnnou GOOGLE_CREDENTIALS_FILE."
        )
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(GOOGLE_CREDS, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    return spreadsheet.worksheet(SHEET_NAME)

def get_existing_ids(worksheet) -> set:
    """Načte existující IDs z column A (kromě hlavičky) aby se nepřidávaly duplicity."""
    all_ids = worksheet.col_values(1)
    return set(str(v) for v in all_ids[1:] if v)  # přeskočit hlavičku

def ensure_header(worksheet):
    first_row = worksheet.row_values(1)
    if first_row != COLUMNS:
        worksheet.update("A1", [COLUMNS])
        print("Hlavička doplněna.")

def append_rows(worksheet, rows: list[list]):
    if not rows:
        return
    # Přidá za existující data (najde první prázdný řádek)
    worksheet.append_rows(rows, value_input_option="USER_ENTERED")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Strava → Google Sheets ===\n")

    token      = get_valid_token()
    activities = fetch_all_activities(token)

    print(f"\nCelkem staženo: {len(activities)} aktivit.")
    print(f"Připojuji se ke Google Sheets (záložka '{SHEET_NAME}')...")

    worksheet = open_sheet()
    ensure_header(worksheet)

    existing_ids = get_existing_ids(worksheet)
    print(f"Existující záznamy v sheetu: {len(existing_ids)}")

    new_activities = [act for act in activities if str(act.get("id", "")) not in existing_ids]

    if not new_activities:
        print("Žádné nové aktivity k přidání.")
    else:
        # Detail (s calories) stahujeme jen při malém počtu nových aktivit.
        # Při hromadném importu by to trvalo hodiny kvůli rate limitu.
        DETAIL_THRESHOLD = 20
        if len(new_activities) <= DETAIL_THRESHOLD:
            print(f"Stahuji detaily pro {len(new_activities)} nových aktivit (calories)...")
            enriched = []
            for i, act in enumerate(new_activities, 1):
                detail = fetch_detail(token, act["id"])
                enriched.append(activity_to_row(detail))
                if i % 10 == 0:
                    print(f"  {i}/{len(new_activities)}")
                time.sleep(0.3)
        else:
            print(f"Hromadný import ({len(new_activities)} aktivit) — calories nebudou vyplněny.")
            enriched = [activity_to_row(act) for act in new_activities]

        print(f"Přidávám {len(enriched)} nových aktivit...")
        chunk = 500
        for i in range(0, len(enriched), chunk):
            append_rows(worksheet, enriched[i:i + chunk])
        print(f"Hotovo! Přidáno {len(enriched)} řádků do záložky '{SHEET_NAME}'.")

if __name__ == "__main__":
    main()
