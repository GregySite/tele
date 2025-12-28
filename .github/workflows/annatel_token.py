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

# On récupère les identifiants depuis les variables d'environnement (Sécurité GitHub)
USER_VAL = os.getenv("ANNATEL_USER")
PASS_VAL = os.getenv("ANNATEL_PASS")

def get_token():
    options = Options()
    options.add_argument("--headless") # Obligatoire sur GitHub Actions
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    token_final = None

    try:
        driver.get("https://client.annatel.tv/auth/login")
        wait = WebDriverWait(driver, 20)
        
        # Connexion
        wait.until(EC.presence_of_element_located((By.XPATH, "//input[@name='login']"))).send_keys(USER_VAL)
        driver.find_element(By.XPATH, "//input[@name='password']").send_keys(PASS_VAL)
        driver.find_element(By.XPATH, "//input[@type='submit']").click()
        
        time.sleep(5)
        driver.get("https://client.annatel.tv/channel/w9")

        # Capture
        start_time = time.time()
        while (time.time() - start_time) < 30:
            logs = driver.get_log("performance")
            for entry in logs:
                message = json.loads(entry["message"])["message"]
                if message["method"] == "Network.requestWillBeSent":
                    url = message["params"]["request"]["url"]
                    if "token=" in url:
                        token_final = url.split("token=")[-1].split("&")[0]
                        break
            if token_final: break
            time.sleep(1)
            
        if token_final:
            # ON SAUVEGARDE DANS UN FICHIER JSON
            data = {"token": token_final, "last_update": time.strftime("%Y-%m-%d %H:%M:%S")}
            with open("token.json", "w") as f:
                json.dump(data, f)
            print(f"Token sauvegardé : {token_final}")
            
    finally:
        driver.quit()

if __name__ == "__main__":
    get_token()
