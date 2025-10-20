# 🧮 POC Excel ↔ Python (Calculs financiers distribués) — UDFKit Edition

## 🎯 Objectif

Ce POC montre comment des **actuaires** peuvent exécuter des calculs Python intensifs à partir d’une **feuille Excel locale**, 
tout en conservant une architecture simple, modulaire et sécurisée.

Grâce au module `udfkit`, un utilisateur peut **ajouter une nouvelle fonction métier**
sans écrire une seule ligne de code FastAPI : il suffit d’écrire la fonction Python et ses modèles d’entrée/sortie.

---

## 🧩 Architecture du projet

```
udfkit_poc/
├── app/
│   ├── main.py          # Point d’entrée FastAPI
│   ├── security.py      # Vérification de la clé API
│   ├── udfkit.py        # Moteur générique d’enregistrement et exécution des UDFs
│   └── my_udfs.py       # Fonctions métiers : npv, duration, scenario
├── tests/
│   └── test_security.py # Tests de sécurité de la clé API
├── .env                 # Clé API locale
├── requirements.txt     # Dépendances Python
└── README.md            # Documentation
```

---

## 🔐 Sécurité — Authentification par clé API

Chaque requête envoyée depuis Excel doit inclure un en-tête :

```
X-API-Key: secret123
```

Définie dans le fichier `.env` :

```
API_KEY=secret123
```

Excel (VBA) lit cette clé dans `Config!B9` et l’ajoute à chaque requête HTTP.

---

## ⚙️ Installation & Lancement

```bash
# 1. Créer un environnement virtuel
python -m venv .venv
.\.venv\Scripts\activate

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Lancer le serveur
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Swagger : [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## 🧠 Le module `udfkit`

Le module `udfkit.py` gère automatiquement :
- L’enregistrement des fonctions via le décorateur `@udf(...)`
- La création automatique des routes FastAPI (`/udf/...` ou `/jobs/...`)
- L’exécution asynchrone dans un `ThreadPoolExecutor`
- Le suivi des états (`queued`, `running`, `done`, `error`)
- La génération des schémas Swagger (OpenAPI)

### Exemple minimal

```python
from pydantic import BaseModel
from app.udfkit import udf

class SquareRequest(BaseModel):
    x: float

class SquareResponse(BaseModel):
    y: float

@udf("square", mode="sync", request_model=SquareRequest, response_model=SquareResponse)
def square(req: SquareRequest) -> SquareResponse:
    return SquareResponse(y=req.x ** 2)
```

➡️ Swagger affichera automatiquement : `POST /udf/square`

---

## 📊 Fonctions métiers disponibles

### 1️⃣ `npv` — Valeur Actuelle Nette

**Entrée :**
```json
{ "cashflows": [100, 100, 100], "rate": 0.05 }
```

**Sortie :**
```json
{
  "npv": 272.32,
  "per_period": [100.0, 95.24, 90.70]
}
```

**Endpoint :** `POST /udf/npv`  
**Type :** Synchrone

---

### 2️⃣ `duration` — Durée moyenne pondérée (Macaulay)

**Entrée :**
```json
{ "cashflows": [100, 100, 100], "rate": 0.05 }
```

**Sortie :**
```json
{
  "npv": 272.32,
  "duration": 1.98,
  "pv_per_period": [100.0, 95.24, 90.70],
  "weights": [0.367, 0.349, 0.333]
}
```

**Endpoint :** `POST /udf/duration`  
**Type :** Synchrone

---

### 3️⃣ `scenario` — Simulation Monte Carlo (asynchrone)

**Entrée :**
```json
{
  "cashflows": [100, 100, 100],
  "rate": 0.05,
  "n_sims": 1000,
  "mu": 0.0,
  "sigma": 0.1
}
```

**Sortie (polling `/jobs/{id}`) :**
```json
{
  "job_id": "uuid",
  "status": "done",
  "result": {
    "npv_mean": 275.10,
    "npv_std": 15.4
  }
}
```

**Endpoints :**
- `POST /jobs/scenario` → soumission du calcul
- `GET /jobs/{job_id}` → polling du résultat

**Type :** Asynchrone

---

## 🧪 Tests automatiques

Fichier : `tests/test_security.py`  
Vérifie que :
- Les appels sans clé sont refusés (`401 Unauthorized`)
- Les appels avec clé valide sont acceptés (`200 OK`)

Exécution :
```bash
pytest -q
```

---

## 🧩 Modules utilisés

| Module | Rôle |
|---------|------|
| **fastapi** | Framework API REST |
| **uvicorn** | Serveur ASGI local |
| **pydantic** | Validation des modèles |
| **numpy** | Calculs numériques |
| **concurrent.futures** | Exécution asynchrone des jobs |
| **pytest** | Tests unitaires |
| **httpx** | Client HTTP pour tests |
| **python-dotenv** | Gestion de la clé API |

---

## 🧭 Bonnes pratiques

- Les actuaires ajoutent simplement une fonction dans `my_udfs.py` :
  ```python
  @udf("nom", mode="sync" ou "async", request_model=..., response_model=...)
  def ma_fonction(req): ...
  ```
- Aucune modification du serveur n’est nécessaire : `udfkit` détecte et publie la nouvelle fonction.
- Les schémas Pydantic garantissent la validation automatique des entrées et sorties.
- Les fonctions `async` utilisent un système de **jobs** avec polling via `/jobs/{id}`.

---

## 🧭 Évolutions possibles

- Authentification par utilisateur (OAuth2, SSO)
- Rotation automatique des clés
- Journalisation et suivi des requêtes
- Déploiement Dockerisé (multi-utilisateurs)
- Intégration à un cluster pour calcul distribué

## 👥 Auteurs & maintenance

**Projet :** POC Excel ↔ Python — UDFKit sécurisé  
**Version :** 2.2  
