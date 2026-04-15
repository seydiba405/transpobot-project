"""
TranspoBot — Backend Intégré (FastAPI + Ollama + MySQL)
Projet GLSi L3 — ESP/UCAD
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import mysql.connector
import os
import re
import requests
import json

app = FastAPI(title="TranspoBot API", version="1.1.0")

# Activation du CORS pour que l'interface HTML puisse communiquer avec l'API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Configuration ──────────────────────────────────────────────
DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "transpobot"),
}

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "phi3"
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))

DB_SCHEMA = """
Tables MySQL disponibles :
vehicules(id, immatriculation, type[bus/minibus/taxi], capacite, statut[actif/maintenance/hors_service], kilometrage, date_acquisition)
chauffeurs(id, nom, prenom, telephone, numero_permis, categorie_permis, disponibilite, vehicule_id, date_embauche)
lignes(id, code, nom, origine, destination, distance_km, duree_minutes)
tarifs(id, ligne_id, type_client[normal/etudiant/senior], prix)
trajets(id, ligne_id, chauffeur_id, vehicule_id, date_heure_depart, date_heure_arrivee, statut[planifie/en_cours/termine/annule], nb_passagers, recette)
incidents(id, trajet_id, type[panne/accident/retard/autre], description, gravite[faible/moyen/grave], date_incident, resolu)
"""

SYSTEM_PROMPT = f"""Tu es TranspoBot, l'assistant intelligent de la compagnie de transport.
Tu aides les gestionnaires à interroger la base de données en langage naturel.
{DB_SCHEMA}
RÈGLES :
1. Génère UNIQUEMENT des requêtes SELECT.
2. Réponds TOUJOURS en JSON : {{"sql": "SELECT...", "explication": "..."}}
3. Limite à 100 lignes maximum.
4. Si la question est une salutation ou n'a pas de besoin SQL clair, réponds : {{"sql": null, "explication": "message utile à l'utilisateur"}}
"""

# ── Fonctions Utilitaires ──────────────────────────────────────
def get_db():
    return mysql.connector.connect(**DB_CONFIG)

def execute_query(sql: str):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql)
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

def est_une_requete_sure(sql_genere):
    if not sql_genere: return False, "Pas de requête générée."
    mots_interdits = ["INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER", "CREATE"]
    requete_haute = sql_genere.upper().strip()
    if not requete_haute.startswith("SELECT"):
        return False, "Seules les consultations (SELECT) sont autorisées."
    for mot in mots_interdits:
        if mot in requete_haute:
            return False, f"Action interdite : {mot}"
    return True, sql_genere

def parse_ollama_response(content: str) -> dict:
    text = (content or "").strip()
    if not text:
        return {}

    # Cas nominal: réponse JSON pure
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # Cas fréquent: JSON entouré de texte
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}

# ── Moteur IA ──────────────────────────────────────────────────
async def ask_llm_ollama(question: str) -> dict:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": f"{SYSTEM_PROMPT}\n\nQuestion client: {question}",
        "stream": False,
        "format": "json",
        "options": {"temperature": 0}
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT_SECONDS)
        response.raise_for_status()
        body = response.json()

        # Ollama peut répondre en 200 avec un champ "error" (ex: model not found).
        if body.get("error"):
            return {"sql": None, "explication": f"Erreur Ollama : {body['error']}"}

        content = body.get("response", "")
        parsed = parse_ollama_response(content)
        if "sql" in parsed:
            return parsed
        if isinstance(parsed.get("query"), dict) and "sql" in parsed["query"]:
            return {
                "sql": parsed["query"].get("sql"),
                "explication": parsed["query"].get("explication", "")
            }
        return {"sql": None, "explication": "Erreur de formatage de l'IA."}
    except requests.exceptions.Timeout:
        return {
            "sql": None,
            "explication": (
                f"Erreur Ollama : délai dépassé après {OLLAMA_TIMEOUT_SECONDS}s. "
                "Le modèle répond trop lentement. Relancez la question ou augmentez OLLAMA_TIMEOUT_SECONDS."
            ),
        }
    except requests.exceptions.ConnectionError:
        return {"sql": None, "explication": "Erreur Ollama : service inaccessible. Lancez `ollama serve`."}
    except Exception as e:
        return {
            "sql": None,
            "explication": f"Erreur Ollama : {str(e)}",
        }

# ── Routes API ─────────────────────────────────────────────────
class ChatMessage(BaseModel):
    question: str

@app.get("/")
def read_root():
    return {"status": "online", "project": "TranspoBot", "author": "Mohamed BA"}

@app.post("/api/chat")
async def chat(msg: ChatMessage):
    try:
        llm_data = await ask_llm_ollama(msg.question)
        sql = llm_data.get("sql")
        explication = llm_data.get("explication", "")
        if not sql:
            return {"answer": explication, "data": [], "sql": None}
        
        valide, msg_secu = est_une_requete_sure(sql)
        if not valide:
            return {"answer": f"⚠️ {msg_secu}", "data": [], "sql": sql}

        data = execute_query(sql)
        return {"answer": explication, "data": data, "sql": sql, "count": len(data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats")
def get_stats():
    queries = {
        "total_trajets":    "SELECT COUNT(*) as n FROM trajets WHERE statut='termine'",
        "trajets_en_cours": "SELECT COUNT(*) as n FROM trajets WHERE statut='en_cours'",
        "vehicules_actifs": "SELECT COUNT(*) as n FROM vehicules WHERE statut='actif'",
        "incidents_ouverts":"SELECT COUNT(*) as n FROM incidents WHERE resolu=FALSE",
    }
    stats = {}
    for key, sql in queries.items():
        res = execute_query(sql)
        stats[key] = res[0]["n"] if res else 0
    return stats

@app.get("/api/vehicules")
def get_vehicules():
    return execute_query("SELECT * FROM vehicules ORDER BY immatriculation")

@app.get("/api/trajets/recent")
def get_trajets_recent():
    return execute_query("""
        SELECT t.*, l.nom as ligne, ch.nom as chauffeur_nom, v.immatriculation
        FROM trajets t
        JOIN lignes l ON t.ligne_id = l.id
        JOIN chauffeurs ch ON t.chauffeur_id = ch.id
        JOIN vehicules v ON t.vehicule_id = v.id
        ORDER BY t.date_heure_depart DESC LIMIT 8
    """)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)