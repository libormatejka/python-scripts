import requests
import time
import xml.etree.ElementTree as ET
import os
import sys
from datetime import datetime
from google.cloud import bigquery # Nová knihovna

# --- KONFIGURACE ---
API_KEY = os.environ.get('PAGESPEED_API_KEY')
# Celá cesta k tabulce, např. "projekt.dataset.tabulka"
BIGQUERY_TABLE_ID = os.environ.get('BIGQUERY_TABLE_ID')

SITEMAP_URL = 'http://collectorboy.cz/sitemap.xml'
POCET_URL_K_TESTOVANI = 5
# ---------------------

def fetch_sitemap_urls(sitemap_url):
    """Načte sitemapu a vrátí seznam URL."""
    print(f"📡 Načítám sitemapu z: {sitemap_url}")
    try:
        response = requests.get(sitemap_url, timeout=30)
        response.raise_for_status()
        namespaces = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        root = ET.fromstring(response.content)
        loc_elements = root.findall('s:url/s:loc', namespaces)
        if not loc_elements:
             loc_elements = root.findall('s:sitemap/s:loc', namespaces)
        urls = [loc.text for loc in loc_elements]
        if not urls:
            print("❌ Chyba: Ve sitemapě nebyly nalezeny žádné <loc> tagy.")
            return None
        print(f"✅ Nalezeno {len(urls)} URL v sitemapě.")
        return urls
    except Exception as e:
        print(f"❌ Chyba při zpracování sitemapy: {e}")
    return None

def check_pagespeed(url_to_check, strategy):
    """
    Spustí test. Místo tisku nyní vrací slovník s metrikami,
    nebo None při chybě.
    """
    print(f"\n⚙️  Testuji: {url_to_check} (Strategie: {strategy})")
    
    api_endpoint = "https.googleapis.com/pagespeedonline/v5/runPagespeed"
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
            print(f"❌ Chyba API: {data['error']['message']}")
            return None

        audits = data.get('lighthouseResult', {}).get('audits', {})
        
        # Získáváme PŘESNÉ ČÍSELNÉ HODNOTY (ne naformátovaný text)
        # Dělíme 1000, abychom převedli milisekundy (ms) na sekundy (s)
        fcp_val = audits.get('first-contentful-paint', {}).get('numericValue', 0) / 1000.0
        lcp_val = audits.get('largest-contentful-paint', {}).get('numericValue', 0) / 1000.0
        # CLS je již ve správném formátu (např. 0.01)
        cls_val = audits.get('cumulative-layout-shift', {}).get('numericValue', 0)
        # Skóre je 0-1, násobíme 100 a převedeme na celé číslo
        score_val = int(data['lighthouseResult']['categories']['performance']['score'] * 100)

        print(f"✅ Výsledky ({strategy}): Skóre: {score_val} | FCP: {fcp_val:.2f}s | LCP: {lcp_val:.2f}s | CLS: {cls_val}")
        
        # Vrátíme slovník s daty
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
    
    return None # V případě chyby vrátíme None

def insert_to_bigquery(client, rows_to_insert):
    """Vloží připravené řádky do BigQuery."""
    if not rows_to_insert:
        print("ℹ️ Nebyla nalezena žádná data k vložení do BigQuery.")
        return

    print(f"\n☁️ Vkládám {len(rows_to_insert)} řádků do BigQuery tabulky: {BIGQUERY_TABLE_ID}")
    
    try:
        # Autentizace proběhla v GitHub Actions, klient ji použije automaticky
        errors = client.insert_rows_json(BIGQUERY_TABLE_ID, rows_to_insert)
        if not errors:
            print("✅ Data úspěšně vložena do BigQuery.")
        else:
            print("❌ Chyba při vkládání dat do BigQuery:")
            for error in errors:
                print(error)
    except Exception as e:
        print(f"❌ Závažná chyba při komunikaci s BigQuery API: {e}")

# --- Hlavní spouštěcí logika ---
def main():
    # Ověření, zda jsou přítomny všechny potřebné "secrets"
    if not API_KEY:
        sys.exit("❌ CHYBA: Secret 'PAGESPEED_API_KEY' nebyl nalezen.")
    if not BIGQUERY_TABLE_ID:
        sys.exit("❌ CHYBA: Secret 'BIGQUERY_TABLE_ID' nebyl nalezen.")
        
    # Autentizace proběhne automaticky díky kroku v YAML
    # Klient si najde přihlašovací údaje v prostředí
    bq_client = bigquery.Client()

    urls_from_sitemap = fetch_sitemap_urls(SITEMAP_URL)
    if not urls_from_sitemap:
        sys.exit("--- Testování ukončeno kvůli chybě sitemapy ---") 

    urls_to_test = urls_from_sitemap[:POCET_URL_K_TESTOVANI]
    strategies_to_test = ['MOBILE', 'DESKTOP']
    
    # Seznam pro sběr všech výsledků
    all_results_to_insert = []
    
    print(f"\n--- Bude testováno prvních {len(urls_to_test)} URL ze sitemapy ---")
    
    total_calls = len(urls_to_test) * len(strategies_to_test)
    current_call = 0

    for url in urls_to_test:
        for strategy in strategies_to_test:
            current_call += 1
            
            # Získáme slovník s metrikami nebo None/STOP
            metrics = check_pagespeed(url, strategy)
            
            if metrics == 'STOP':
                print("\n!!! ZASTAVENO: API vrátilo chybu 429. Ukončuji skript.")
                break # Ukončí vnitřní smyčku (strategie)
            
            # Pokud byl test úspěšný (vrátil data)
            if metrics:
                # Připravíme řádek pro BigQuery
                now = datetime.utcnow()
                row = {
                    "DATE": now.strftime("%Y-%m-%d"),
                    "TIMESTAMP": now.isoformat() + "Z", # Formát pro BigQuery TIMESTAMP
                    "URL": url,
                    "DEVICE_CATEGORY": strategy,
                    "FCP": metrics["fcp"],
                    "LCP": metrics["lcp"],
                    "CLS": metrics["cls"],
                    "OVERALL_SCORE": metrics["score"]
                }
                all_results_to_insert.append(row)

            if current_call < total_calls and metrics != 'STOP':
                print("--- ⏱️ Pauza 0.5s ---")
                time.sleep(0.5)
        
        if metrics == 'STOP':
            break # Ukončí vnější smyčku (URL)

    # Po dokončení všech testů vložíme sebraná data do BigQuery
    insert_to_bigquery(bq_client, all_results_to_insert)

    print("\n--- 🎉 Všechny úlohy dokončeny ---")

if __name__ == "__main__":
    main()
