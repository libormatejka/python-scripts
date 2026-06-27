# 📚 Import knihoven
import os
import time
import requests
import zipfile
import datetime
from io import StringIO
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import pandas as pd

try:
    from google.colab import files as colab_files
    IN_COLAB = True
except ImportError:
    IN_COLAB = False

# 🔧 Konfigurace — přes env proměnné
MODE = os.environ.get("IG_MODE", "csv")          # "csv" nebo "saved"
IG_USERNAME = os.environ.get("IG_USERNAME", "")
IG_PASSWORD = os.environ.get("IG_PASSWORD", "")
IG_COLLECTION = os.environ.get("IG_COLLECTION", "")  # název kolekce, prázdné = všechny uložené
CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTTsguvmetBw9DNbjPzbWMBlHydJgG6osQDVrdNqMYjZ7flrRdtYgTVQDXVODfRI14V8Bi_HyRpeEet/pub?gid=0&single=true&output=csv"


def load_urls_from_csv(url):
    resp = requests.get(url)
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text), header=None)
    return df[0].dropna().tolist()


def instagram_login(driver):
    print("🔐 Přihlašuji se na Instagram...")
    driver.get("https://www.instagram.com/accounts/login/")
    time.sleep(4)

    driver.save_screenshot("debug_login_page.png")
    print(f"📸 Screenshot: {driver.title} | URL: {driver.current_url}")

    wait = WebDriverWait(driver, 20)

    # Cookies dialog
    try:
        cookie_btn = WebDriverWait(driver, 6).until(EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(text(),'Allow') or contains(text(),'Povolit') or contains(text(),'Accept') or contains(text(),'Přijmout')]")
        ))
        cookie_btn.click()
        time.sleep(2)
    except Exception:
        pass

    # Přihlášení — Instagram používá name="email" a name="pass"
    username_field = wait.until(EC.presence_of_element_located((By.NAME, "email")))
    username_field.clear()
    username_field.send_keys(IG_USERNAME)

    password_field = wait.until(EC.presence_of_element_located((By.NAME, "pass")))
    password_field.send_keys(IG_PASSWORD)
    password_field.submit()
    time.sleep(6)

    driver.save_screenshot("debug_after_login.png")
    print(f"📸 Po přihlášení: {driver.title} | URL: {driver.current_url}")

    # Popup "Uložit přihlašovací údaje?" / Notifikace
    for _ in range(2):
        try:
            btn = WebDriverWait(driver, 6).until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(text(),'Not Now') or contains(text(),'Teď ne') or contains(text(),'Nyní ne')]")
            ))
            btn.click()
            time.sleep(2)
        except Exception:
            pass

    print("✅ Přihlášení proběhlo.")


def find_collection_url(driver):
    """Najde URL konkrétní kolekce podle názvu na stránce uložených příspěvků."""
    driver.get(f"https://www.instagram.com/{IG_USERNAME}/saved/")
    time.sleep(3)

    collection_name_lower = IG_COLLECTION.lower()
    links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/saved/']")
    for link in links:
        href = link.get_attribute("href")
        text = link.text.strip().lower()
        if not href or "/saved/" not in href or href.rstrip("/").endswith("/saved"):
            continue
        if collection_name_lower in text:
            print(f"✅ Nalezena kolekce '{link.text.strip()}': {href}")
            return href

    # Záloha: hledej název v potomcích odkazu
    for link in links:
        href = link.get_attribute("href")
        if not href or href.rstrip("/").endswith("/saved"):
            continue
        try:
            inner_text = link.get_attribute("innerText").strip().lower()
        except Exception:
            continue
        if collection_name_lower in inner_text:
            print(f"✅ Nalezena kolekce: {href}")
            return href

    print(f"❌ Kolekce '{IG_COLLECTION}' nebyla nalezena.")
    return None


def scrape_posts_from_page(driver):
    """Projede aktuální stránku (scrolluje) a vrátí URL všech příspěvků."""
    post_urls = set()
    last_height = 0

    while True:
        links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/p/']")
        for link in links:
            href = link.get_attribute("href")
            if href and "/p/" in href:
                post_urls.add(href.split("?")[0])

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

    return post_urls


def get_saved_post_urls(driver):
    if IG_COLLECTION:
        print(f"📂 Hledám kolekci '{IG_COLLECTION}' pro @{IG_USERNAME}...")
        collection_url = find_collection_url(driver)
        if not collection_url:
            return []
        driver.get(collection_url)
        time.sleep(3)
    else:
        print(f"📂 Načítám všechny uložené příspěvky pro @{IG_USERNAME}...")
        driver.get(f"https://www.instagram.com/{IG_USERNAME}/saved/")
        time.sleep(3)

    post_urls = scrape_posts_from_page(driver)
    print(f"✅ Nalezeno {len(post_urls)} příspěvků.")
    return list(post_urls)


def download_image_from_post(driver, url):
    parsed = urlparse(url)
    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    try:
        driver.get(clean_url)
        time.sleep(5)
    except Exception as e:
        print(f"❌ Nelze přistoupit na stránku: {e}")
        return None

    articles = driver.find_elements(By.TAG_NAME, "article")
    search_root = articles[0] if articles else driver
    images = search_root.find_elements(By.TAG_NAME, "img")

    best_src = None
    best_area = 0
    for img in images:
        src = img.get_attribute("src")
        if not src or "cdninstagram.com" not in src or src.endswith(".svg"):
            continue
        # Vylouč profilové fotky (mají t51.2885-19 v URL)
        if "t51.2885-19" in src:
            continue
        w = driver.execute_script("return arguments[0].naturalWidth", img) or 0
        h = driver.execute_script("return arguments[0].naturalHeight", img) or 0
        if w * h > best_area:
            best_area = w * h
            best_src = src

    if not best_src:
        return None

    post_id = os.path.basename(parsed.path.strip("/"))
    filename = f"{post_id}.jpg"
    try:
        r = requests.get(best_src)
        r.raise_for_status()
        with open(filename, "wb") as f:
            f.write(r.content)
        print(f"✅ Uloženo jako {filename} ({int(best_area**0.5)}px)")
        return filename
    except Exception as exc:
        print(f"❌ Chyba při stahování: {exc}")
        return None


# ── Nastavení Chrome ──────────────────────────────────────────────────────────
chrome_options = Options()
chrome_options.add_argument("--headless=new")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--window-size=1920x1080")
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option("useAutomationExtension", False)

service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=chrome_options)

# Skryj webdriver příznak před JavaScriptem
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
    "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
})

# ── Získání seznamu URL ───────────────────────────────────────────────────────
if MODE == "saved":
    if not IG_USERNAME or not IG_PASSWORD:
        print("❌ Chybí IG_USERNAME nebo IG_PASSWORD.")
        driver.quit()
        exit(1)
    instagram_login(driver)
    urls = get_saved_post_urls(driver)
else:
    print(f"📥 Stahuji CSV z: {CSV_URL}")
    urls = load_urls_from_csv(CSV_URL)
    print(f"✅ Načteno {len(urls)} URL pro zpracování.")

# ── Stahování obrázků ─────────────────────────────────────────────────────────
downloaded_images = []
for url in urls:
    print(f"\n🌐 Zpracovávám: {url}")
    filename = download_image_from_post(driver, url)
    if filename:
        downloaded_images.append(filename)
    else:
        print("⚠️ Obrázek se nepodařilo najít.")

driver.quit()

# ── ZIP archiv ────────────────────────────────────────────────────────────────
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

    if IN_COLAB:
        colab_files.download(zip_filename)
