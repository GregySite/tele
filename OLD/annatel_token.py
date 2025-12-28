import json
import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

USER_VAL = os.getenv("ANNATEL_USER")
PASS_VAL = os.getenv("ANNATEL_PASS")

def get_token():
    print("Démarrage - Mode Ultra-Léger")
    
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    # On bloque les images pour aller plus vite et éviter les timeouts
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # STRATÉGIE ANTI-TIMEOUT : On n'attend pas le chargement complet (eager)
    options.page_load_strategy = 'eager'
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    token_final = None

    try:
        print("Accès à la page login...")
        driver.get("https://client.annatel.tv/auth/login")
        
        # On attend manuellement l'élément, c'est plus sûr que le load global
        wait = WebDriverWait(driver, 30)
        
        print("Saisie des identifiants...")
        user_field = wait.until(EC.presence_of_element_located((By.NAME, "login")))
        user_field.send_keys(USER_VAL)
        driver.find_element(By.NAME, "password").send_keys(PASS_VAL)
        
        print("Clic connexion...")
        driver.find_element(By.XPATH, "//input[@type='submit']").click()
        
        time.sleep(5)
        
        print("Navigation vers W9...")
        driver.get("https://client.annatel.tv/channel/w9")

        print("Recherche du token...")
        start_time = time.time()
        while (time.time() - start_time) < 40:
            logs = driver.get_log("performance")
            for entry in logs:
                msg = json.loads(entry["message"])["message"]
                if msg["method"] == "Network.requestWillBeSent":
                    url = msg["params"]["request"]["url"]
                    if "token=" in url:
                        token_final = url.split("token=")[-1].split("&")[0]
                        break
            if token_final: break
            time.sleep(2)

        if token_final:
            data = {"token": token_final, "last_update": time.strftime("%d/%m/%Y %H:%M:%S")}
            with open("token.json", "w") as f:
                json.dump(data, f)
            print(f"OK: Token trouvé")
        else:
            print("ERREUR: Token non trouvé dans le flux")

    except Exception as e:
        print(f"CRASH : {str(e)}")
    finally:
        driver.quit()

if __name__ == "__main__":
    get_token()
