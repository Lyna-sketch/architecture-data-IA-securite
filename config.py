"""Configuration partagée par tous les scripts.

Les secrets (clés S3, clé de l'OCR) sont lus dans le fichier .env,
qui n'est jamais commité (il est listé dans .gitignore).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Dossier du projet (là où se trouve ce fichier). Les chemins sont construits à partir
# de lui : ils restent valides sur n'importe quelle machine.
DOSSIER_PROJET = Path(__file__).parent

# Charge le fichier .env dans les variables d'environnement
load_dotenv(DOSSIER_PROJET / ".env")

# --- S3 ---
BUCKET = os.getenv("S3_BUCKET", "factures")

# --- Dossiers de données ---
DOSSIER_LANDING = DOSSIER_PROJET / "data" / "landing"   # PDF téléchargés depuis S3
DOSSIER_BRONZE = DOSSIER_PROJET / "data" / "bronze"     # texte brut extrait + métadonnées (Parquet)
DOSSIER_SILVER = DOSSIER_PROJET / "data" / "silver"     # tables propres et typées (Parquet)
DOSSIER_EVALUATION = DOSSIER_PROJET / "data" / "evaluation"  # textes OCR et résultats de l'étape 5
FICHIER_ENTREPOT = DOSSIER_PROJET / "data" / "entrepot.duckdb"  # entrepôt DuckDB (vues uniquement)

# --- OCR ---
OCR_URL = os.getenv("OCR_BASE_URL", "")      # adresse de l'API du modèle
OCR_CLE = os.getenv("OCR_API_KEY", "")       # clé d'API (secret)
OCR_MODELE = os.getenv("OCR_MODEL", "")      # nom du modèle
OCR_DPI = int(os.getenv("OCR_DPI", "130"))  # résolution des images envoyées à l'OCR (130 DPI ≈ 1540 px en A4)
