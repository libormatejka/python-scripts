import requests
import time
import os
import sys
from datetime import datetime
from google.cloud import bigquery

# --- KONFIGURACE ---
API_KEY = os.environ.get('PAGESPEED_API_KEY')
BIGQUERY_TABLE_ID = os.environ.get('BIGQUERY_TABLE_ID')
URLS_TO_TEST = os.environ.get('URLS_TO_TEST', '')  # Seznam URL oddělený novými řádky
# ---------------------

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

def parse_urls_from_config(urls_string):
    """Načte URL ze stringu odděleného novými řádky."""
    if not urls_string or not urls_string.strip():
        print("❌ Chyba: Seznam URL je prázdný.")
        return None
    
    # Rozdělíme podle nových řádků a odstraníme prázdné řádky a mezery
    urls = [url.strip() for url in urls_string.strip().split('\n') if url.strip()]
    
    if not urls:
        print("❌ Chyba: Nepodařilo se načíst žádné platné URL.")
        return None
    
    print(f"✅ Načteno {len(urls)} URL z konfigurace.")
    print(f"\n📋 Seznam URL k testování:")
    for i, url in enumerate(urls, 1):
        print(f"   {i}. {url}")
    
    return urls

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
    if not URLS_TO_TEST:
        sys.exit("❌ CHYBA: Secret 'URLS_TO_TEST' nebyl nalezen nebo je prázdný.")
        
    bq_client = bigquery.Client()

    # Načteme všechny URL z konfigurace
    urls_to_test = parse_urls_from_config(URLS_TO_TEST)
    if not urls_to_test:
        sys.exit("--- Testování ukončeno kvůli chybě v konfiguraci URL ---") 
    
    strategies_to_test = ['MOBILE', 'DESKTOP']
    all_results_to_insert = []
    
    print(f"\n{'='*60}")
    print(f"--- Zahajuji testování {len(urls_to_test)} URL ---")
    print(f"{'='*60}")
    
    total_calls = len(urls_to_test) * len(strategies_to_test)
    current_call = 0

    for url in urls_to_test:
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