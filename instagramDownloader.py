# 🔧 Instalace potřebných nástrojů
!apt-get update -qq
!apt install -y chromium-chromedriver zip
!cp /usr/lib/chromium-browser/chromedriver /usr/bin
!pip install selenium --quiet pandas

# 📚 Import knihoven
import sys
import os
import time
import requests
import zipfile
import datetime
from io import StringIO
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from google.colab import files
import pandas as pd

# 🌐 URL externího CSV (jediný sloupec s Instagram URL)
CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTTsguvmetBw9DNbjPzbWMBlHydJgG6osQDVrdNqMYjZ7flrRdtYgTVQDXVODfRI14V8Bi_HyRpeEet/pub?gid=0&single=true&output=csv"

# 📥 Stažení a načtení CSV dat

def load_urls_from_csv(url):
    resp = requests.get(url)
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text), header=None)
    return df[0].dropna().tolist()

print(f"📥 Stahuji CSV z: {CSV_URL}")
urls = load_urls_from_csv(CSV_URL)
print(f"✅ Načteno {len(urls)} URL pro zpracování.")

# 🛠️ Nastavení Chrome prohlížeče
sys.path.insert(0, '/usr/lib/chromium-browser/chromedriver')
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--window-size=1920x1080")

driver = webdriver.Chrome(options=chrome_options)

downloaded_images = []

# 🔁 Stáhnout obrázky z Instagramu
for url in urls:
    parsed = urlparse(url)
    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    print(f"\n🌐 Zpracovávám: {clean_url}")
    try:
        driver.get(clean_url)
        time.sleep(5)
    except Exception as e:
        print(f"❌ Nelze přistoupit na stránku: {e}")
        continue

    images = driver.find_elements(By.TAG_NAME, "img")
    found = False
    for img in images:
        src = img.get_attribute("src")
        if src and "cdninstagram.com" in src and not src.endswith(".svg"):
            post_id = os.path.basename(parsed.path.strip("/"))
            filename = f"{post_id}.jpg"
            try:
                r = requests.get(src)
                r.raise_for_status()
                with open(filename, "wb") as f:
                    f.write(r.content)
                print(f"✅ Uloženo jako {filename}")
                downloaded_images.append(filename)
            except Exception as exc:
                print(f"❌ Chyba při stahování: {exc}")
            found = True
            break
    if not found:
        print("⚠️ Obrázek se nepodařilo najít.")

driver.quit()

# 📅 Vytvoření ZIP archivu s dnešním datem
# Odstranění duplicitních souborů
unique_images = list(dict.fromkeys(downloaded_images))

if not unique_images:
    print("⚠️ Žádné obrázky ke zpracování. Žádný archiv nebude vytvořen.")
else:
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    zip_filename = f"{today_str}_Instagram_Export.zip"
    with zipfile.ZipFile(zip_filename, 'w') as zipf:
        for fname in unique_images:
            zipf.write(os.path.abspath(fname), arcname=fname)
            print(f"📦 Přidáno do ZIP: {fname}")
    print(f"\n📦 Archiv vytvořen: {zip_filename} (velikost: {os.path.getsize(zip_filename)} bytes)")

    # ⬇️ Stažení ZIP archivu
    files.download(zip_filename)
