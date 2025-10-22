import requests
import time
import xml.etree.ElementTree as ET
import os  # Pro čtení proměnných prostředí (API klíč)
import sys # Pro případné ukončení skriptu s chybou

# --- KONFIGURACE ---
# API klíč se bezpečně načte z GitHub Secrets (proměnné prostředí)
API_KEY = os.environ.get('PAGESPEED_API_KEY') 

# URL sitemapy je nyní nastavena napevno zde
SITEMAP_URL = 'http://collectorboy.cz/sitemap.xml'

# Počet URL, které chceme otestovat
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
    """Spustí PageSpeed test pro JEDNU URL a JEDNU STRATEGII."""
    
    if not API_KEY:
        print("❌ ZÁVAŽNÁ CHYBA: Nebyl nalezen API klíč v proměnné prostředí PAGESPEED_API_KEY.")
        sys.exit(1) # Ukončí celý skript s chybovým kódem

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
            print(f"❌ Chyba API pro {url_to_check} ({strategy}): {data['error']['message']}")
            return False

        audits = data.get('lighthouseResult', {}).get('audits', {})
        score = data['lighthouseResult']['categories']['performance']['score'] * 100
        fcp = audits.get('first-contentful-paint', {}).get('displayValue', 'N/A')
        lcp = audits.get('largest-contentful-paint', {}).get('displayValue', 'N/A')
        cls = audits.get('cumulative-layout-shift', {}).get('displayValue', 'N/A')

        print(f"✅ Výsledky ({strategy}): Skóre: {score:.0f}/100 | FCP: {fcp} | LCP: {lcp} | CLS: {cls}")
        return True

    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP Chyba pro {url_to_check} ({strategy}): {e.response.status_code} {e.response.reason}")
        if e.response.status_code == 429: 
            return 'STOP' 
    except Exception as e:
        print(f"❌ Neočekávaná chyba pro {url_to_check} ({strategy}): {e}")
    
    return False

# --- Hlavní spouštěcí logika ---
def main():
    # URL sitemapy se nyní bere z konstanty SITEMAP_URL definované výše
    urls_from_sitemap = fetch_sitemap_urls(SITEMAP_URL)
    
    if not urls_from_sitemap:
        sys.exit("--- Testování ukončeno kvůli chybě sitemapy ---") 

    urls_to_test = urls_from_sitemap[:POCET_URL_K_TESTOVANI]
    strategies_to_test = ['MOBILE', 'DESKTOP']
    
    print(f"\n--- Bude testováno prvních {len(urls_to_test)} URL ze sitemapy ---")
    
    total_calls = len(urls_to_test) * len(strategies_to_test)
    current_call = 0

    for url in urls_to_test:
        for strategy in strategies_to_test:
            current_call += 1
            status = check_pagespeed(url, strategy)
            
            if status == 'STOP':
                print("\n!!! ZASTAVENO: API vrátilo chybu 429 (Too Many Requests). Ukončuji skript.")
                sys.exit(1) 

            if current_call < total_calls:
                print("--- ⏱️ Pauza 0.5s (ochrana před rate limitem) ---")
                time.sleep(0.5)
                
        print("-------------------------------------------------") 

    print("\n--- 🎉 Všechny úlohy dokončeny ---")

if __name__ == "__main__":
    main()
