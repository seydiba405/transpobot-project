import requests
import json

# 1. Fonction pour générer le SQL via Ollama
def generate_sql_with_ollama(user_question):
    try:
        with open('prompt.txt', 'r', encoding='utf-8') as f:
            system_instructions = f.read()
    except FileNotFoundError:
        return "Erreur : Le fichier prompt.txt est introuvable."

    url = "http://localhost:11434/api/generate"
    payload = {
        "model": "llama3",
        "prompt": f"{system_instructions}\n\nQuestion client: {user_question}",
        "stream": False,
        "options": {"temperature": 0}
    }

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        result = response.json()
        return result.get("response", "").strip()
    except Exception as e:
        return f"Erreur de connexion à Ollama : {str(e)}"

# 2. Fonction de sécurité (SORTIE de la boucle while)
def est_une_requete_sure(sql_genere):
    mots_interdits = ["INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER", "CREATE"]
    requete_haute = sql_genere.upper().strip()
    
    if not requete_haute.startswith("SELECT"):
        return False, "Seules les consultations sont autorisées."
    
    for mot in mots_interdits:
        if mot in requete_haute:
            return False, f"Action interdite détectée : {mot}"
            
    return True, sql_genere

# 3. Boucle principale d'exécution
if __name__ == "__main__":
    print("=== Assistant TranspoBot (Sécurité Activée) ===")
    print("Tapez 'quitter' pour arrêter.\n")
    
    while True:
        user_input = input("Vous : ")
        
        if user_input.lower() in ["quitter", "exit", "quit"]:
            break
            
        # Appel de l'IA
        sql_brut = generate_sql_with_ollama(user_input)
        
        # --- VERIFICATION DE SECURITE ---
        est_valide, resultat = est_une_requete_sure(sql_brut)
        
        if est_valide:
            print(f"Robot (SQL) : {resultat}\n")
        else:
            print(f"⚠️ BLOCAGE SÉCURITÉ : {resultat}\n")