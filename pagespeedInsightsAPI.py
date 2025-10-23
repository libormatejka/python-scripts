import requests
import time
import os
import sys
from datetime import datetime
from google.cloud import bigquery
import gspread
from google.oauth2 import service_account

# --- KONFIGURACE ---
API_KEY = os.environ.get('PAGESPEED_API_KEY')
BIGQUERY_TABLE_ID = os.environ.get('BIGQUERY_TABLE_ID')
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')  # ID spreadsheetu
SHEET_NAME = os.environ.get('SHEET_NAME', 'Sheet1')  # Název listu, default 'Sheet1'
# ---------------------

def fetch_urls_from_spreadsheet(spreadsheet_id, sheet_name):
    """Načte URL a Category z Google Spreadsheet."""
    print(f"📊 Načítám data z Google Spreadsheet...")
    print(f"   Spreadsheet ID: {spreadsheet_id}")
    print(f"   List: {sheet_name}")
    
    try:
        # Použijeme stejné credentials jako pro BigQuery
        credentials = service_account.Credentials.from_service_account_file(
            os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'),
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
        )
        
        gc = gspread.authorize(credentials)
        spreadsheet = gc.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(sheet_name)
        
        # Načteme všechna data
        all_records = worksheet.get_all_records()
        
        if not all_records:
            print("❌ Chyba: Spreadsheet neobsahuje žádná data.")
            return None
        
        # Vytvoříme seznam URL s jejich kategoriemi
        url_data = []
        for i, record in enumerate(all_records, 1):
            url = record.get('URL', '').strip()
            category = record.get('Category', '').strip()
            
            if url:  # Přidáme pouze řádky s URL
                url_data.append({
                    'url': url,
                    'category': category if category else 'Uncategorized'
                })
        
        if not url_data:
            print("❌ Chyba: Ve spreadsheetu nebyly nalezeny žádné platné URL.")
            return None
        
        print(f"✅ Načteno {len(url_data)} URL z spreadsheetu.")
        print(f"\n📋 První 3 URL k testování:")
        for i, data in enumerate(url_data[:3], 1):
            print(f"   {i}. {data['url']} (Kategorie: {data['category']})")
        
        return url_data
        
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"❌ Chyba: Spreadsheet s ID '{spreadsheet_id}' nebyl nalezen.")
        print("   Zkontroluj, zda je spreadsheet sdílený se service accountem.")
        return None
    except gspread.exceptions.WorksheetNotFound:
        print(f"❌ Chyba: List '{sheet_name}' nebyl ve spreadsheetu nalezen.")
        return None
    except Exception as e:
        print(f"❌ Chyba při načítání spreadsheetu: {e}")
        import traceback
        print(f"🔍 Traceback: {traceback.format_exc()}")
        return None

def check_pagespeed(url_to_check, strategy):
    """Spustí PageSpeed test a vrací metriky."""
    print(f"\n⚙️  Testuji: {url_to_check} (Strategie: {strategy})")
    
    api_endpoint = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    params = {
        'url': url_to_check, 
        'key': API_KEY, 
        'strategy': strategy, 
        'category': 'PERFORMANCE'
    }

    try:
        response = requests.get(api_endpoint, params=params, timeout=120)
        response.raise_for_status() 
        data = response.json()

        if 'error' in data:
            print(f"❌ Chyba API: {data['error'].get('message', 'Neznámá chyba')}")
            return None

        audits = data.get('lighthouseResult', {}).get('audits', {})
        
        fcp_val = audits.get('first-contentful-paint', {}).get('numericValue', 0) / 1000.0
        lcp_val = audits.get('largest-contentful-paint', {}).get('numericValue', 0) / 1000.0
        cls_val = audits.get('cumulative-layout-shift', {}).get('numericValue', 0)
        score_val = int(data['lighthouseResult']['categories']['performance']['score'] * 100)

        print(f"✅ Výsledky ({strategy}): Skóre: {score_val} | FCP: {fcp_val:.2f}s | LCP: {lcp_val:.2f}s | CLS: {cls_val}")
        
        return {
            "fcp": fcp_val,
            "lcp": lcp_val,
            "cls": cls_val,
            "score": score_val
        }

    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP Chyba: {e.response.status_code} {e.response.reason}")
        if e.response.status_code == 429: return 'STOP'
    except Exception as e:
        print(f"❌ Neočekávaná chyba: {e}")
    
    return None

def insert_to_bigquery(client, rows_to_insert):
    """Vloží připravené řádky do BigQuery."""
    if not rows_to_insert:
        print("ℹ️ Nebyla nalezena žádná data k vložení do BigQuery.")
        return

    print(f"\n☁️ Vkládám {len(rows_to_insert)} řádků do BigQuery tabulky: {BIGQUERY_TABLE_ID}")
    
    try:
        errors = client.insert_rows_json(BIGQUERY_TABLE_ID, rows_to_insert)
        if not errors:
            print("✅ Data úspěšně vložena do BigQuery.")
        else:
            print("❌ Chyba při vkládání dat do BigQuery:")
            for error in errors:
                print(error)
    except Exception as e:
        print(f"❌ Závažná chyba při komunikaci s BigQuery API: {e}")

def main():
    if not API_KEY:
        sys.exit("❌ CHYBA: Secret 'PAGESPEED_API_KEY' nebyl nalezen.")
    if not BIGQUERY_TABLE_ID:
        sys.exit("❌ CHYBA: Secret 'BIGQUERY_TABLE_ID' nebyl nalezen.")
    if not SPREADSHEET_ID:
        sys.exit("❌ CHYBA: Variable 'SPREADSHEET_ID' nebyla nalezena.")
        
    bq_client = bigquery.Client()

    # Načteme URL a kategorie ze spreadsheetu
    url_data = fetch_urls_from_spreadsheet(SPREADSHEET_ID, SHEET_NAME)
    if not url_data:
        sys.exit("--- Testování ukončeno kvůli chybě při načítání spreadsheetu ---") 
    
    strategies_to_test = ['MOBILE', 'DESKTOP']
    all_results_to_insert = []
    
    print(f"\n{'='*60}")
    print(f"--- Zahajuji testování {len(url_data)} URL ---")
    print(f"{'='*60}")
    
    total_calls = len(url_data) * len(strategies_to_test)
    current_call = 0

    for data in url_data:
        url = data['url']
        category = data['category']
        
        for strategy in strategies_to_test:
            current_call += 1
            print(f"\n[{current_call}/{total_calls}]", end=" ")
            
            metrics = check_pagespeed(url, strategy)
            
            if metrics == 'STOP':
                print("\n!!! ZASTAVENO: API vrátilo chybu 429. Ukončuji skript.")
                break
            
            if metrics:
                now = datetime.utcnow()
                row = {
                    "DATE": now.strftime("%Y-%m-%d"),
                    "TIMESTAMP": now.isoformat() + "Z",
                    "URL": url,
                    "CATEGORY": category,  # ← PŘIDÁNA KATEGORIE
                    "DEVICE_CATEGORY": strategy,
                    "FCP": metrics["fcp"],
                    "LCP": metrics["lcp"],
                    "CLS": metrics["cls"],
                    "OVERALL_SCORE": metrics["score"]
                }
                all_results_to_insert.append(row)

            if current_call < total_calls and metrics != 'STOP':
                time.sleep(0.5)
        
        if metrics == 'STOP':
            break

    print(f"\n{'='*60}")
    print(f"📊 Celkem získáno {len(all_results_to_insert)} úspěšných měření")
    print(f"{'='*60}")

    insert_to_bigquery(bq_client, all_results_to_insert)
    print("\n--- 🎉 Všechny úlohy dokončeny ---")

if __name__ == "__main__":
    main()