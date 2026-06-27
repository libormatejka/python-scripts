# Strava Downloader

Skript stahuje všechny aktivity z účtu Strava a zapisuje je do Google Sheets. Každý den ráno se spouští automaticky přes GitHub Actions.

**Cílový spreadsheet:** [Data-python](https://docs.google.com/spreadsheets/d/1MxnYvXjVUorTTe05UV-OxBV-LwZmSBMtXtwL8YFS6k8/edit?gid=1282557719#gid=1282557719)

---

## Přehled fungování

```
GitHub Actions (každý den 6:00 UTC)
        │
        ▼
stravaDownloader.py
        │
        ├─► Strava API (OAuth2) ──► stáhne všechny aktivity
        │
        └─► Google Sheets API ──► zapíše nové řádky do záložky "Data-python"
```

Skript je **idempotentní** — před zápisem porovná `id` aktivit s tím, co už v sheetu je, a přidá pouze nové. Bezpečné spouštět opakovaně.

---

## Jednorázové nastavení

### 1. Strava API aplikace

1. Přejdi na [strava.com/settings/api](https://www.strava.com/settings/api)
2. Vytvoř novou aplikaci (název libovolný)
3. Do pole **Authorization Callback Domain** napiš: `localhost`
4. Zkopíruj **Client ID** a **Client Secret**

### 2. Google Service Account

1. Otevři [console.cloud.google.com](https://console.cloud.google.com) a vytvoř (nebo vyber) projekt
2. Aktivuj dvě API:
   - **Google Sheets API**
   - **Google Drive API**
3. Jdi do **IAM & Admin → Service Accounts** → vytvoř nový service account
4. Na service accountu klikni na **Keys → Add Key → JSON** — stáhni soubor
5. Otevři [spreadsheet](https://docs.google.com/spreadsheets/d/1MxnYvXjVUorTTe05UV-OxBV-LwZmSBMtXtwL8YFS6k8) a sdílej ho s emailem service accountu (najdeš ho v JSON jako `client_email`) — stačí role **Editor**

### 3. První lokální spuštění (získání Refresh Tokenu)

```bash
# Nainstaluj závislosti
pip install requests gspread google-auth

# Ulož Google credentials JSON vedle skriptu
cp ~/Downloads/google-credentials.json ./google_credentials.json

# Nastav env proměnné
export STRAVA_CLIENT_ID="12345"
export STRAVA_CLIENT_SECRET="abc123..."

# Spusť — otevře se prohlížeč pro Strava autorizaci
python stravaDownloader.py
```

Po autorizaci v prohlížeči se vytvoří soubor `.strava_token.json`. Otevři ho a zkopíruj hodnotu `refresh_token` — budeš ji potřebovat jako GitHub secret.

---

## GitHub Secrets (musíš přidat v Settings → Secrets and variables → Actions)

| Secret | Kde to najdeš | Příklad |
|---|---|---|
| `STRAVA_CLIENT_ID` | Strava API stránka | `12345` |
| `STRAVA_CLIENT_SECRET` | Strava API stránka | `abc123def456...` |
| `STRAVA_REFRESH_TOKEN` | soubor `.strava_token.json` → pole `refresh_token` | `xyz789...` |
| `GOOGLE_CREDENTIALS_JSON` | obsah celého staženeho JSON souboru service accountu | `{"type":"service_account",...}` |

### Jak přidat secret na GitHub

1. Jdi do repozitáře → **Settings → Secrets and variables → Actions**
2. Klikni **New repository secret**
3. Zadej název a hodnotu dle tabulky výše
4. Zopakuj pro všechny 4 secrets

> **`GOOGLE_CREDENTIALS_JSON`** — zkopíruj celý obsah JSON souboru (otevři v textovém editoru, Ctrl+A, Ctrl+C).

---

## Spouštění

### Automaticky
GitHub Action se spustí každý den v **6:00 UTC** (= 7:00 nebo 8:00 v ČR dle letního času).

### Ručně
Na GitHubu jdi do **Actions → Strava → Google Sheets (denní sync) → Run workflow**.

### Lokálně
```bash
export STRAVA_CLIENT_ID="..."
export STRAVA_CLIENT_SECRET="..."
# refresh token není potřeba lokálně — skript použije .strava_token.json
python stravaDownloader.py
```

---

## Struktura dat v Google Sheets

| Sloupec | Popis | Jednotka / formát |
|---|---|---|
| `id` | Unikátní ID aktivity na Strava | číslo |
| `date` | Datum aktivity | `YYYY-MM-DD` |
| `name` | Název aktivity | text |
| `type` | Typ sportu (Run, Ride, Swim…) | text |
| `distance (meters)` | Vzdálenost | metry |
| `kudos` | Počet kudos | číslo |
| `elev_low` | Nejnižší bod trasy | metry n. m. |
| `elev_high` | Nejvyšší bod trasy | metry n. m. |
| `average_heartrate` | Průměrná tepová frekvence | bpm |
| `max_heartrate` | Maximální tepová frekvence | bpm |
| `moving_time` | Čas v pohybu | `hh:mm:ss` |
| `elapsed_time (seconds)` | Celkový čas aktivity | sekundy |
| `calories` | Spálené kalorie | kcal |
| `elevation` | Nejvyšší bod trasy (= elev_high) | metry n. m. |
| `total_elevation_gain` | Celkové převýšení | metry |
| `pace` | Tempo (pro běh) | `mm:ss /km` |
| `average_speed` | Průměrná rychlost | km/h |
| `max_speed` | Maximální rychlost | km/h |
| `workout_type` | Typ tréninku (závodní, lehký…) | číslo (Strava kód) |

---

## Env proměnné skriptu

| Proměnná | Povinná | Default | Popis |
|---|---|---|---|
| `STRAVA_CLIENT_ID` | ano | — | Client ID ze Strava API |
| `STRAVA_CLIENT_SECRET` | ano | — | Client Secret ze Strava API |
| `STRAVA_REFRESH_TOKEN` | v CI | — | Refresh token (GitHub Actions, obchází browser flow) |
| `STRAVA_TOKEN_FILE` | ne | `.strava_token.json` | Cesta k souboru s tokenem |
| `GOOGLE_CREDENTIALS_FILE` | ano | `google_credentials.json` | Cesta k Service Account JSON |

---

## Soubory

```
python-scripts/
├── stravaDownloader.py          # hlavní skript
├── stravaDownloader.md          # tato dokumentace
├── google_credentials.json      # Google Service Account klíč (NEPŘIDÁVAT do gitu!)
├── .strava_token.json           # Strava OAuth token (NEPŘIDÁVAT do gitu!)
└── .github/workflows/
    └── stravaDownloader.yml     # GitHub Action
```

> Ujisti se, že `google_credentials.json` a `.strava_token.json` jsou v `.gitignore`.
