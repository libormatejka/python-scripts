import os
import sys
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

CLIENT_ID         = os.environ.get("STRAVA_CLIENT_ID", "")
CLIENT_SECRET     = os.environ.get("STRAVA_CLIENT_SECRET", "")
TOKEN_FILE        = os.environ.get("STRAVA_TOKEN_FILE", ".strava_token.json")
REFRESH_TOKEN_ENV = os.environ.get("STRAVA_REFRESH_TOKEN", "")

GOOGLE_CREDS   = os.environ.get("GOOGLE_CREDENTIALS_FILE", "google_credentials.json")
SPREADSHEET_ID = "1MxnYvXjVUorTTe05UV-OxBV-LwZmSBMtXtwL8YFS6k8"
SHEET_NAME     = "Data-python"

REDIRECT_URI = "http://localhost:8765/callback"
AUTH_URL     = "https://www.strava.com/oauth/authorize"
TOKEN_URL    = "https://www.strava.com/oauth/token"
API_BASE     = "https://www.strava.com/api/v3"
SCOPES       = "activity:read_all"

COLUMNS = [
    "id", "date", "name", "type", "distance (meters)", "kudos",
    "elev_low", "elev_high", "average_heartrate", "max_heartrate",
    "moving_time", "elapsed_time (seconds)", "calories", "elevation",
    "total_elevation_gain", "pace", "average_speed", "max_speed", "workout_type",
]

# ── Logging ───────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def log_section(title: str):
    print(f"\n{'─' * 50}", flush=True)
    log(title)
    print('─' * 50, flush=True)

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
    log("Obnovuji Strava access token...")
    resp = requests.post(TOKEN_URL, data={
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type":    "refresh_token",
        "refresh_token": token["refresh_token"],
    })
    if resp.status_code == 401:
        raise RuntimeError(
            "401 Unauthorized při obnově tokenu — refresh token je neplatný nebo revokovaný.\n"
            "Vygeneruj nový refresh token a aktualizuj GitHub secret STRAVA_REFRESH_TOKEN.\n"
            "Návod: https://www.strava.com/settings/api"
        )
    resp.raise_for_status()
    new_token = resp.json()
    save_token(new_token)
    expires = datetime.fromtimestamp(new_token["expires_at"], tz=timezone.utc).strftime("%H:%M:%S UTC")
    scope = new_token.get("scope", "není v odpovědi")
    log(f"Token obnoven, platí do {expires}. Scope: {scope}")
    return new_token

def get_valid_token() -> dict:
    token = load_token()
    if token:
        if token.get("expires_at", 0) - time.time() < 60:
            token = refresh_token(token)
        else:
            log("Strava token načten ze souboru, platný.")
        return token

    if REFRESH_TOKEN_ENV:
        log("Používám STRAVA_REFRESH_TOKEN z env proměnné...")
        synthetic = {"refresh_token": REFRESH_TOKEN_ENV, "expires_at": 0}
        return refresh_token(synthetic)

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
    log("Token uložen.")
    return token

def oauth_flow() -> dict:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError(
            "Nastav STRAVA_CLIENT_ID a STRAVA_CLIENT_SECRET jako env proměnné.\n"
            "Aplikaci vytvoříš na https://www.strava.com/settings/api"
        )

    manual_code = os.environ.get("STRAVA_AUTH_CODE", "").strip()
    if manual_code:
        log("Používám STRAVA_AUTH_CODE z env proměnné...")
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
    log("Cekam na callback (port 8765)...")
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
        used  = resp.headers.get("X-RateLimit-Usage", "?")
        limit = resp.headers.get("X-RateLimit-Limit", "?")
        reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 900))
        wait  = max(reset - int(time.time()), 60)
        reset_str = datetime.fromtimestamp(reset, tz=timezone.utc).strftime("%H:%M:%S UTC")
        log(f"Rate limit dosažen (usage: {used}/{limit}) — čekám {wait}s do {reset_str}...")
        time.sleep(wait)
        log("Rate limit vyprsel, pokracuji...")
        return api_get(endpoint, token, params)
    if resp.status_code == 403:
        raise RuntimeError(
            f"403 Forbidden na {endpoint}\n"
            f"Strava odpověď: {resp.text}\n"
            "Scope tokenu není dostatečný nebo app nemá přístup k aktivitám."
        )
    resp.raise_for_status()
    return resp.json()

def fetch_all_activities(token: dict) -> list[dict]:
    activities = []
    page = 1
    t_start = time.time()
    log("Zahajuji stahování aktivit ze Strava...")
    while True:
        t_page = time.time()
        batch = api_get("/athlete/activities", token, {"per_page": 100, "page": page})
        if not batch:
            break
        activities.extend(batch)
        elapsed = time.time() - t_start
        log(f"  Stránka {page}: +{len(batch)} aktivit → celkem {len(activities)} ({elapsed:.1f}s)")
        page += 1
        time.sleep(0.4)
    log(f"Stahování dokončeno: {len(activities)} aktivit za {time.time() - t_start:.1f}s")
    return activities

def fetch_detail(token: dict, activity_id: int) -> dict:
    return api_get(f"/activities/{activity_id}", token)

# ── Transformace ──────────────────────────────────────────────────────────────

def activity_to_row(act: dict) -> list:
    raw_date = act.get("start_date_local", "")
    return [
        act.get("id", ""),
        raw_date[:10] if raw_date else "",
        act.get("name", ""),
        act.get("sport_type") or act.get("type", ""),
        act.get("distance", ""),
        act.get("kudos_count", ""),
        act.get("elev_low", ""),
        act.get("elev_high", ""),
        act.get("average_heartrate", ""),
        act.get("max_heartrate", ""),
        act.get("moving_time", ""),
        act.get("elapsed_time", ""),
        act.get("calories", ""),
        act.get("elev_high", ""),
        act.get("total_elevation_gain", ""),
        act.get("average_cadence", ""),
        act.get("average_speed", ""),
        act.get("max_speed", ""),
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
    creds  = Credentials.from_service_account_file(GOOGLE_CREDS, scopes=scopes)
    client = gspread.authorize(creds)
    for attempt in range(1, 6):
        try:
            spreadsheet = client.open_by_key(SPREADSHEET_ID)
            return spreadsheet.worksheet(SHEET_NAME)
        except Exception as e:
            if attempt == 5:
                raise
            wait = attempt * 10
            log(f"Google Sheets nedostupné: {e} — čekám {wait}s (pokus {attempt}/5)...")
            time.sleep(wait)

def get_existing_ids(worksheet) -> set:
    log("Načítám existující ID z Google Sheets...")
    all_ids = worksheet.col_values(1)
    ids = set(str(v) for v in all_ids[1:] if v)
    log(f"Nalezeno {len(ids)} existujících záznamů v sheetu.")
    return ids

def ensure_header(worksheet):
    first_row = worksheet.row_values(1)
    if first_row != COLUMNS:
        worksheet.update("A1", [COLUMNS])
        log("Hlavička doplněna.")

def append_rows(worksheet, rows: list[list]):
    if not rows:
        return
    worksheet.append_rows(rows, value_input_option="USER_ENTERED")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    t_total = time.time()
    print("=" * 50)
    log("START: Strava → Google Sheets")
    print("=" * 50)

    log_section("1/4  Google Sheets — ověření připojení")
    log(f"Spreadsheet ID: {SPREADSHEET_ID}")
    log(f"Záložka: {SHEET_NAME}")
    worksheet = open_sheet()
    ensure_header(worksheet)
    log("Google Sheets OK.")

    log_section("2/4  Strava — autentizace")
    token = get_valid_token()

    log_section("3/4  Strava — stahování aktivit")
    activities = fetch_all_activities(token)

    log_section("4/4  Google Sheets — zápis nových aktivit")
    existing_ids   = get_existing_ids(worksheet)
    new_activities = [act for act in activities if str(act.get("id", "")) not in existing_ids]
    log(f"Nových aktivit k zapsání: {len(new_activities)}")

    if not new_activities:
        log("Žádné nové aktivity — sheet je aktuální.")
    else:
        DETAIL_THRESHOLD = 20
        if len(new_activities) <= DETAIL_THRESHOLD:
            log(f"Stahuji detaily pro {len(new_activities)} aktivit (calories)...")
            enriched = []
            for i, act in enumerate(new_activities, 1):
                detail = fetch_detail(token, act["id"])
                enriched.append(activity_to_row(detail))
                log(f"  Detail {i}/{len(new_activities)}: {act.get('name', act['id'])}")
                time.sleep(0.3)
        else:
            log(f"Hromadný import ({len(new_activities)} aktivit) — calories přeskočeny.")
            enriched = [activity_to_row(act) for act in new_activities]

        chunk = 500
        for i in range(0, len(enriched), chunk):
            batch = enriched[i:i + chunk]
            log(f"Zapisuji řádky {i+1}–{i+len(batch)} do Google Sheets...")
            append_rows(worksheet, batch)
            log(f"  Dávka zapsána.")

        log(f"Zapsáno {len(enriched)} nových řádků do záložky '{SHEET_NAME}'.")

    print("\n" + "=" * 50)
    log(f"HOTOVO — celkový čas: {time.time() - t_total:.1f}s")
    print("=" * 50)

if __name__ == "__main__":
    main()
