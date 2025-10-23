import requests
import time
import os
import sys
from datetime import datetime
from google.cloud import bigquery
import gspread
from google.oauth2 import service_account
from statistics import median

# --- KONFIGURACE ---
API_KEY = os.environ.get('PAGESPEED_API_KEY')
BIGQUERY_TABLE_ID = os.environ.get('BIGQUERY_TABLE_ID')
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')
SHEET_NAME = os.environ.get('SHEET_NAME', 'Sheet1')
POCET_OPAKOVANI = 3
# ---------------------

def fetch_urls_from_spreadsheet(spreadsheet_id, sheet_name):
    """Načte URL a Category z Google Spreadsheet."""
    print(f"📊 Načítám data z Google Spreadsheet...")
    print(f"   Spreadsheet ID: {spreadsheet_id}")
    print(f"   List: {sheet_name}")
    
    try:
        credentials = service_account.Credentials.from_service_account_file(
            os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'),
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
        )
        
        gc = gspread.authorize(credentials)
        spreadsheet = gc.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(sheet_name)
        
        all_records = worksheet.get_all_records()
        
        if not all_records:
            print("❌ Chyba: Spreadsheet neobsahuje žádná data.")
            return None
        
        url_data = []
        for i, record in enumerate(all_records, 1):
            url = record.get('URL', '').strip()
            category = record.get('Category', '').strip()
            
            if url:
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

def test_url_multiple_times(url, strategy, pocet_opakovani=3):
    """
    Otestuje URL několikrát a vrátí medián z výsledků.
    """
    print(f"\n⚙️  Testuji: {url} (Strategie: {strategy})")
    print(f"   Počet měření: {pocet_opakovani}x")
    
    all_measurements = []
    
    for i in range(pocet_opakovani):
        print(f"   📊 Měření {i+1}/{pocet_opakovani}...", end=" ")
        
        metrics = check_pagespeed(url, strategy)
        
        if metrics == 'STOP':
            return 'STOP'
        
        if metrics:
            all_measurements.append(metrics)
            print(f"Skóre: {metrics['score']} | FCP: {metrics['fcp']:.2f}s | LCP: {metrics['lcp']:.2f}s")
        else:
            print("Selhalo")
        
        if i < pocet_opakovani - 1:
            time.sleep(0.5)
    
    if not all_measurements:
        print("   ❌ Všechna měření selhala")
        return None
    
    fcp_values = [m['fcp'] for m in all_measurements]
    lcp_values = [m['lcp'] for m in all_measurements]
    cls_values = [m['cls'] for m in all_measurements]
    score_values = [m['score'] for m in all_measurements]
    
    median_metrics = {
        'fcp': median(fcp_values),
        'lcp': median(lcp_values),
        'cls': median(cls_values),
        'score': int(median(score_values))
    }
    
    print(f"   ✅ MEDIÁN: Skóre: {median_metrics['score']} | "
          f"FCP: {median_metrics['fcp']:.2f}s | "
          f"LCP: {median_metrics['lcp']:.2f}s | "
          f"CLS: {median_metrics['cls']:.4f}")
    
    return median_metrics

def insert_to_bigquery(client, rows_to_insert):
    """Vloží připravené řádky do BigQuery."""
    if not rows_to_insert:
        return

    try:
        errors = client.insert_rows_json(BIGQUERY_TABLE_ID, rows_to_insert)
        if not errors:
            print(f"   ☁️ ✅ Uloženo do BigQuery ({len(rows_to_insert)} řádků)")
        else:
            print("   ❌ Chyba při vkládání dat do BigQuery:")
            for error in errors:
                print(f"      {error}")
    except Exception as e:
        print(f"   ❌ Chyba při komunikaci s BigQuery: {e}")

def main():
    if not API_KEY:
        sys.exit("❌ CHYBA: Secret 'PAGESPEED_API_KEY' nebyl nalezen.")
    if not BIGQUERY_TABLE_ID:
        sys.exit("❌ CHYBA: Secret 'BIGQUERY_TABLE_ID' nebyl nalezen.")
    if not SPREADSHEET_ID:
        sys.exit("❌ CHYBA: Variable 'SPREADSHEET_ID' nebyla nalezena.")
        
    bq_client = bigquery.Client()

    url_data = fetch_urls_from_spreadsheet(SPREADSHEET_ID, SHEET_NAME)
    if not url_data:
        sys.exit("--- Testování ukončeno kvůli chybě při načítání spreadsheetu ---") 
    
    strategies_to_test = ['MOBILE', 'DESKTOP']
    
    print(f"\n{'='*60}")
    print(f"--- Zahajuji testování {len(url_data)} URL ---")
    print(f"--- Každá URL bude testována {POCET_OPAKOVANI}x pro každou strategii ---")
    print(f"--- Výsledky budou průběžně ukládány do BigQuery ---")
    print(f"{'='*60}")
    
    total_tests = len(url_data) * len(strategies_to_test)
    current_test = 0
    total_saved = 0

    for data in url_data:
        url = data['url']
        category = data['category']
        
        for strategy in strategies_to_test:
            current_test += 1
            print(f"\n{'='*60}")
            print(f"[Test {current_test}/{total_tests}] URL: {url[:50]}... | Kategorie: {category}")
            print(f"{'='*60}")
            
            median_metrics = test_url_multiple_times(url, strategy, POCET_OPAKOVANI)
            
            if median_metrics == 'STOP':
                print("\n!!! ZASTAVENO: API vrátilo chybu 429. Ukončuji skript.")
                break
            
            if median_metrics:
                now = datetime.utcnow()
                row = {
                    "DATE": now.strftime("%Y-%m-%d"),
                    "TIMESTAMP": now.isoformat() + "Z",
                    "URL": url,
                    "CATEGORY": category,
                    "DEVICE_CATEGORY": strategy,
                    "FCP": median_metrics["fcp"],
                    "LCP": median_metrics["lcp"],
                    "CLS": median_metrics["cls"],
                    "OVERALL_SCORE": median_metrics["score"]
                }
                
                # OKAMŽITĚ uložíme do BigQuery
                insert_to_bigquery(bq_client, [row])
                total_saved += 1
            
            if current_test < total_tests:
                time.sleep(1)
        
        if median_metrics == 'STOP':
            break

    print(f"\n{'='*60}")
    print(f"📊 Celkem uloženo {total_saved} úspěšných měření do BigQuery")
    print(f"{'='*60}")
    print("\n--- 🎉 Všechny úlohy dokončeny ---")

if __name__ == "__main__":
    main()