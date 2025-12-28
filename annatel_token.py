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

# --- RÉCUPÉRATION DES SECRETS GITHUB ---
USER_VAL = os.getenv("ANNATEL_USER")
PASS_VAL = os.getenv("ANNATEL_PASS")

def get_token():
    print("Démarrage de la récupération du token...")
    
    # --- CONFIGURATION CHROME POUR SERVEUR (GITHUB ACTIONS) ---
    options = Options()
    options.add_argument("--headless=new") # Mode sans fenêtre (obligatoire)
    options.add_argument("--no-sandbox")   # Nécessaire pour les droits root Linux
    options.add_argument("--disable-dev-shm-usage") # Utilise la RAM système au lieu de /dev/shm
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--remote-allow-origins=*")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    # Installation du driver Chrome
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    # Timeout global pour éviter les blocages infinis
    driver.set_page_load_timeout(60)
    token_final = None

    try:
        # 1. Connexion
        print("Navigation vers la page de login...")
        driver.get("https://client.annatel.tv/auth/login")
        wait = WebDriverWait(driver, 20)
        
        print("Remplissage des identifiants...")
        wait.until(EC.presence_of_element_located((By.XPATH, "//input[@name='login']"))).send_keys(USER_VAL)
        driver.find_element(By.XPATH, "//input[@name='password']").send_keys(PASS_VAL)
        
        print("Clic sur le bouton submit...")
        driver.find_element(By.XPATH, "//input[@type='submit']").click()
        
        # Pause pour laisser la session se créer
        time.sleep(5)
        
        # 2. Accès à la chaîne pour générer le flux réseau
        print("Navigation vers la page W9...")
        driver.get("https://client.annatel.tv/channel/w9")

        # 3. Analyse des logs de performance (Réseau)
        print("Analyse du réseau pour trouver le token...")
        start_time = time.time()
        # On cherche pendant 40 secondes max
        while (time.time() - start_time) < 40:
            logs = driver.get_log("performance")
            for entry in logs:
                message = json.loads(entry["message"])["message"]
                
                # On filtre les requêtes réseau sortantes
                if message["method"] == "Network.requestWillBeSent":
                    url_requete = message["params"]["request"]["url"]
                    
                    if "token=" in url_requete:
                        print(f"URL avec token détectée : {url_requete}")
                        # On isole le token
                        token_extrais = url_requete.split("token=")[-1]
                        token_final = token_extrais.split("&")[0]
                        break
            
            if token_final:
                break
            time.sleep(2) # On vérifie toutes les 2 secondes

        # 4. Sauvegarde du résultat
        if token_final:
            data = {
                "token": token_final, 
                "last_update": time.strftime("%d/%m/%Y %H:%M:%S")
            }
            # On écrit le fichier à la racine
            with open("token.json", "w") as f:
                json.dump(data, f)
            print(f"SUCCÈS : Token {token_final} enregistré dans token.json")
        else:
            print("ERREUR : Token non trouvé dans les requêtes réseau.")

    except Exception as e:
        print(f"UNE ERREUR EST SURVENUE : {str(e)}")
        
    finally:
        print("Fermeture du navigateur.")
        driver.quit()

if __name__ == "__main__":
    get_token()
