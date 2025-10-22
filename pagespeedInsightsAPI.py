import requests
import time
import xml.etree.ElementTree as ET
import os
import sys
import json
from datetime import datetime
from google.cloud import bigquery

# --- KONFIGURACE ---
API_KEY = os.environ.get('PAGESPEED_API_KEY')
BIGQUERY_TABLE_ID = os.environ.get('BIGQUERY_TABLE_ID')

SITEMAP_URL = 'https://www.collectorboy.cz/sitemap.xml'
POCET_URL_K_TESTOVANI = 3
# ---------------------

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'cs-CZ,cs;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
}

def fetch_sitemap_urls(sitemap_url):
    """Načte sitemapu a vrátí seznam URL."""
    print(f"📡 Načítám sitemapu z: {sitemap_url}")
    try:
        response = requests.get(sitemap_url, headers=HEADERS, timeout=30)
        print(f"🔍 Status kód sitemapy: {response.status_code}")
        response.raise_for_status()
        
        namespaces = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        root = ET.fromstring(response.content)
        loc_elements = root.findall('s:url/s:loc', namespaces)
        
        if not loc_elements:
            loc_elements = root.findall('s:sitemap/s:loc', namespaces)
            print("🔍 Použity <sitemap> tagy místo <url> tagů")
        
        # Automaticky převedeme http:// na https://
        urls = []
        for loc in loc_elements:
            url = loc.text
            if url.startswith('http://'):
                url = url.replace('http://', 'https://')
                print(f"🔄 Převedeno: {loc.text} → {url}")
            urls.append(url)
        
        if not urls:
            print("❌ Chyba: Ve sitemapě nebyly nalezeny žádné <loc> tagy.")
            return None
        
        print(f"✅ Nalezeno {len(urls)} URL v sitemapě.")
        print(f"\n🔍 První 3 URL ze sitemapy:")
        for i, url in enumerate(urls[:3], 1):
            print(f"   {i}. {url}")
        
        return urls
    except Exception as e:
        print(f"❌ Chyba při zpracování sitemapy: {e}")
        import traceback
        print(f"🔍 Traceback: {traceback.format_exc()}")
    return None

def check_pagespeed(url_to_check, strategy):
    """
    Spustí test. Místo tisku nyní vrací slovník s metrikami,
    nebo None při chybě.
    """
    print(f"\n⚙️  Testuji: {url_to_check} (Strategie: {strategy})")
    
    api_endpoint = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    params = {
        'url': url_to_check, 
        'key': API_KEY, 
        'strategy': strategy, 
        'category': 'PERFORMANCE'
    }

    print(f"🔍 PageSpeed API endpoint: {api_endpoint}")
    print(f"🔍 Parametry: url={url_to_check}, strategy={strategy}")

    try:
        response = requests.get(api_endpoint, params=params, timeout=120)
        print(f"🔍 PageSpeed API status kód: {response.status_code}")
        
        response.raise_for_status() 
        data = response.json()

        if 'error' in data:
            print(f"❌ Chyba API: {data['error'].get('message', 'Neznámá chyba')}")
            print(f"🔍 Celý error objekt:")
            print(json.dumps(data['error'], indent=2, ensure_ascii=False))
            
            # Pokud je to 404, zkusíme ještě debug
            if 'code' in data['error'] and data['error']['code'] == 404:
                print(f"\n🔍 PageSpeed API nemůže najít URL: {url_to_check}")
                print(f"🔍 Možné důvody:")
                print(f"   - URL neexistuje nebo není přístupná")
                print(f"   - Web blokuje PageSpeed boty")
                print(f"   - Problém s DNS nebo SSL certifikátem")
                print(f"   - robots.txt blokuje přístup")
            
            return None

        # Kontrola, zda máme všechna potřebná data
        if 'lighthouseResult' not in data:
            print(f"❌ Chybí 'lighthouseResult' v odpovědi API")
            print(f"🔍 Klíče v odpovědi: {list(data.keys())}")
            return None

        audits = data.get('lighthouseResult', {}).get('audits', {})
        
        # Získáváme PŘESNÉ ČÍSELNÉ HODNOTY
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
        print(f"🔍 Response text: {e.response.text[:500]}")
        if e.response.status_code == 429: 
            return 'STOP'
    except Exception as e:
        print(f"❌ Neočekávaná chyba: {e}")
        import traceback
        print(f"🔍 Traceback: {traceback.format_exc()}")
    
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
        import traceback
        print(f"🔍 Traceback: {traceback.format_exc()}")

def main():
    print("🚀 Spouštím PageSpeed monitoring...")
    print(f"🔍 Python verze: {sys.version}")
    print(f"🔍 Aktuální čas (UTC): {datetime.utcnow()}")
    
    # Ověření secrets
    if not API_KEY:
        sys.exit("❌ CHYBA: Secret 'PAGESPEED_API_KEY' nebyl nalezen.")
    else:
        print(f"✅ PageSpeed API key nalezen (délka: {len(API_KEY)} znaků)")
    
    if not BIGQUERY_TABLE_ID:
        sys.exit("❌ CHYBA: Secret 'BIGQUERY_TABLE_ID' nebyl nalezen.")
    else:
        print(f"✅ BigQuery Table ID: {BIGQUERY_TABLE_ID}")
    
    try:
        bq_client = bigquery.Client()
        print(f"✅ BigQuery klient inicializován")
    except Exception as e:
        print(f"❌ Chyba při inicializaci BigQuery klienta: {e}")
        import traceback
        print(f"🔍 Traceback: {traceback.format_exc()}")
        sys.exit(1)

    urls_from_sitemap = fetch_sitemap_urls(SITEMAP_URL)
    if not urls_from_sitemap:
        sys.exit("--- Testování ukončeno kvůli chybě sitemapy ---") 

    urls_to_test = urls_from_sitemap[:POCET_URL_K_TESTOVANI]
    strategies_to_test = ['MOBILE', 'DESKTOP']
    
    all_results_to_insert = []
    
    print(f"\n{'='*60}")
    print(f"--- Bude testováno prvních {len(urls_to_test)} URL ze sitemapy ---")
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
                print(f"✅ Data připravena k vložení")
            else:
                print(f"⚠️ Žádná data nebyla získána pro tuto URL")

            if current_call < total_calls and metrics != 'STOP':
                print("--- ⏱️ Pauza 0.5s ---")
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