"""Configuration centralisée.

Toutes les valeurs viennent des variables d'environnement, elles-mêmes chargées
depuis le fichier `.env` (non versionné). Aucun secret n'est écrit dans le code.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Racine du dépôt : deux niveaux au-dessus de src/factures/config.py
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Charge .env dans os.environ. Une variable déjà définie dans le shell est prioritaire
# (pratique en production, où l'on n'utilise pas de fichier .env).
load_dotenv(PROJECT_ROOT / ".env")

S3_BUCKET = os.getenv("S3_BUCKET", "factures")
S3_PREFIX = os.getenv("S3_PREFIX", "")

# Chemins relatifs à la racine du projet : ils restent valides sur votre machine,
# chez un collègue ou dans un conteneur.
DATA_DIR = PROJECT_ROOT / os.getenv("DATA_DIR", "data")
LANDING_DIR = DATA_DIR / "landing"  # zone d'arrivée : les PDF tels que téléchargés
