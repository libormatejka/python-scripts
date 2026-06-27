# Python Scripts

Kolekce automatizovaných skriptů pro stahování a ukládání dat do Google Sheets / BigQuery.
Každý skript běží automaticky přes GitHub Actions.

| Skript | Co dělá | Spouštění |
|---|---|---|
| [strava/](strava/) | Stahuje aktivity ze Strava → Google Sheets | každý den 6:00 UTC |
| [instagram/](instagram/) | Stahuje obrázky z Instagramu → ZIP | každý den 4:00 UTC |
| [pagespeed/](pagespeed/) | PageSpeed testy → BigQuery + Google Sheets | každý den 3:00 UTC |
| [gpx-mapper/](gpx-mapper/) | Heatmapa GPX tras → PNG | manuálně (Docker) |

---

## Strava Downloader

Stahuje všechny aktivity ze Strava a zapisuje je do záložky **Data-python** v Google Sheets.
Skript přidává pouze nové aktivity — bezpečné spouštět opakovaně.

**Spreadsheet:** [Data-python](https://docs.google.com/spreadsheets/d/1MxnYvXjVUorTTe05UV-OxBV-LwZmSBMtXtwL8YFS6k8/edit?gid=1282557719#gid=1282557719)

### Jak to funguje

```
GitHub Actions (každý den 6:00 UTC)
        │
        ▼
strava/stravaDownloader.py
        │
        ├─► Strava API (OAuth2) ──► stáhne všechny aktivity
        │
        └─► Google Sheets API ──► zapíše nové řádky do záložky "Data-python"
```

### Jednorázové nastavení

#### 1. Strava API aplikace

1. Přejdi na [strava.com/settings/api](https://www.strava.com/settings/api)
2. Vytvoř novou aplikaci (název libovolný)
3. Do pole **Authorization Callback Domain** napiš `localhost`
4. Zkopíruj **Client ID** a **Client Secret**

#### 2. Google Service Account

1. Otevři [console.cloud.google.com](https://console.cloud.google.com)
2. Aktivuj **Google Sheets API** a **Google Drive API**
3. Vytvoř Service Account — v poli Role nic nevybírej
4. **Keys → Add Key → JSON** — stáhni soubor, ulož jako `google_credentials.json` do kořene repozitáře
5. Otevři spreadsheet → **Sdílet** → vlož `client_email` ze staženého JSON → role **Editor**

#### 3. Spuštění přes Docker (první spuštění = získání tokenu)

```bash
# Zkopíruj a vyplň .env
cp strava/.env.example .env

# Vytvoř prázdný token soubor
touch .strava_token.json

# Spusť
cd strava
docker compose run --rm strava
```

Skript vypíše URL do terminálu — otevři ji v prohlížeči, klikni **Authorize**.
Pokud prohlížeč zobrazí chybu (ERR_CONNECTION_REFUSED), zkopíruj kód z URL a spusť:

```bash
docker compose run --rm -e STRAVA_AUTH_CODE=<kod_z_url> strava
```

Po úspěšném spuštění se vytvoří `.strava_token.json` s platným tokenem.

#### 4. GitHub Secrets

Přidej v **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Kde to najdeš |
|---|---|
| `STRAVA_CLIENT_ID` | [strava.com/settings/api](https://www.strava.com/settings/api) |
| `STRAVA_CLIENT_SECRET` | [strava.com/settings/api](https://www.strava.com/settings/api) |
| `STRAVA_REFRESH_TOKEN` | obsah `.strava_token.json` → pole `refresh_token` |
| `GOOGLE_CREDENTIALS_JSON` | celý obsah souboru `google_credentials.json` (Ctrl+A, Ctrl+C) |

### Spouštění

**Automaticky** — každý den v 6:00 UTC (= 7:00 / 8:00 v ČR)

**Ručně na GitHubu** — Actions → *Strava → Google Sheets (denní sync)* → **Run workflow**

**Lokálně přes Docker:**
```bash
cd strava
docker compose run --rm strava
```

### Struktura dat

| Sloupec | Popis | Formát |
|---|---|---|
| `id` | ID aktivity | číslo |
| `date` | Datum | `YYYY-MM-DD` |
| `name` | Název aktivity | text |
| `type` | Typ sportu (Run, Ride…) | text |
| `distance (meters)` | Vzdálenost | metry |
| `kudos` | Počet kudos | číslo |
| `elev_low` | Nejnižší bod trasy | m n. m. |
| `elev_high` | Nejvyšší bod trasy | m n. m. |
| `average_heartrate` | Průměrná tepová frekvence | bpm |
| `max_heartrate` | Maximální tepová frekvence | bpm |
| `moving_time` | Čas v pohybu | `hh:mm:ss` |
| `elapsed_time (seconds)` | Celkový čas | sekundy |
| `calories` | Spálené kalorie | kcal |
| `elevation` | Nejvyšší bod trasy | m n. m. |
| `total_elevation_gain` | Celkové převýšení | metry |
| `pace` | Tempo | `mm:ss /km` |
| `average_speed` | Průměrná rychlost | km/h |
| `max_speed` | Maximální rychlost | km/h |
| `workout_type` | Typ tréninku | číslo (Strava kód) |

### Env proměnné

| Proměnná | Povinná | Default | Popis |
|---|---|---|---|
| `STRAVA_CLIENT_ID` | ano | — | Client ID ze Strava API |
| `STRAVA_CLIENT_SECRET` | ano | — | Client Secret ze Strava API |
| `STRAVA_REFRESH_TOKEN` | jen v CI | — | Refresh token pro GitHub Actions |
| `STRAVA_AUTH_CODE` | jen při prvním spuštění | — | Jednorázový auth kód z OAuth URL |
| `STRAVA_TOKEN_FILE` | ne | `.strava_token.json` | Cesta k token souboru |
| `GOOGLE_CREDENTIALS_FILE` | ano | `google_credentials.json` | Cesta ke Google Service Account JSON |

### Soubory

```
python-scripts/
├── strava/
│   ├── stravaDownloader.py     # hlavní skript
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── requirements.txt
│   └── .env.example
├── .github/workflows/
│   └── stravaDownloader.yml    # GitHub Action
├── google_credentials.json     # Google Service Account klíč (v .gitignore!)
├── .strava_token.json          # Strava OAuth token (v .gitignore!)
└── .env                        # env proměnné (v .gitignore!)
```
