# architecture-data-IA-securite

De la facture PDF (native ou scannée) à un agent IA qui répond aux questions sur les factures :

```
PDF (bucket S3) ─► extraction / OCR ─► bronze ─► silver ─► entrepôt DuckDB ─► serveur MCP ─► agent IA
```

## Installation

1. Installer [uv](https://docs.astral.sh/uv/) (installe Python et les bibliothèques du projet) :

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

   Puis ouvrir un nouveau terminal (ou `source ~/.local/bin/env`).

2. Installer les bibliothèques :

   ```bash
   uv sync
   ```

3. Créer le fichier `.env` et y coller vos clés (il n'est jamais commité) :

   ```bash
   cp .env.example .env
   ```

## Lancer chaque étape

| Étape | Commande | Ce qu'elle fait |
|---|---|---|
| 1 | `uv run python etape1_recuperer.py` | télécharge les nouvelles factures dans `data/landing/` et classe chaque PDF en « texte » ou « image » |
| 2 | `uv run python etape2_ocr.py facture_P-2025-0002_scan.pdf` (option : `200` pour 200 DPI) | envoie la page au modèle d'OCR, affiche le texte reconnu et le temps de traitement |
| 3 | `uv run python etape3_bronze.py` (option : `5` pour limiter à 5 fichiers) | extrait le texte de chaque nouveau PDF (pypdf ou OCR) et l'ajoute à la couche bronze `data/bronze/` |
| 4 | `uv run python etape4_silver.py` | transforme le bronze en tables propres et typées dans `data/silver/` |
| 5 | `uv run python etape5_evaluation.py` (option : liste de DPI, ex. `100 300`) | compare l'extraction OCR à la vérité terrain `verite_terrain.csv`, champ par champ, à 50 / 72 / 130 / 200 DPI |

### La couche bronze (`data/bronze/run_*.parquet`)

- Chaque exécution **ajoute** un nouveau fichier ; les précédents ne sont jamais modifiés.
- Un fichier est reconnu par l'**empreinte sha256** de son contenu : relancer le script ne retraite rien.
- Si l'OCR est indisponible, la ligne est enregistrée avec `statut = erreur` et le fichier est retraité au lancement suivant.
- Colonnes : `sha256`, `nom_fichier`, `taille_octets`, `nb_pages`, `type_pdf`, `methode`, `modele_ocr`, `ocr_dpi`, `texte`, `duree_s`, `date_ingestion`, `statut`, `erreur`.

### La couche silver (`data/silver/`)

| Fichier | Contenu |
|---|---|
| `factures.parquet` | une ligne par facture, avec `statut_qualite` (`valide` / `signalee`) et `anomalies` |
| `lignes_facture.parquet` | une ligne par ligne de facture (désignation, quantité, prix, TVA, total) |
| `quarantaine.parquet` | documents rejetés, avec leur `motif` |

- Montants en `decimal(12,2)` (calcul exact au centime), dates en `date`.
- **Rejetée** (quarantaine) : champ obligatoire manquant ou illisible, date invalide, doublon (même fournisseur + même numéro).
- **Signalée** (gardée, à vérifier) : HT + TVA ≠ TTC, somme des lignes ≠ HT, quantité × prix ≠ total de ligne, échéance avant émission, SIRET invalide.
- Le silver est recalculé entièrement à partir du bronze à chaque lancement.

## Fichiers

| Fichier | Rôle |
|---|---|
| `config.py` | configuration commune (lit `.env`) |
| `etape1_recuperer.py` | étape 1 : téléchargement S3 + détection texte / image |
| `etape2_ocr.py` | étape 2 : appel du modèle LightOnOCR-3 |
| `etape3_bronze.py` | étape 3 : couche bronze (texte brut + traçabilité, incrémental) |
| `etape4_silver.py` | étape 4 : couche silver (parsing, typage, contrôles qualité, quarantaine) |
| `etape5_verite_terrain.py` | étape 5 : prépare le brouillon de vérité terrain (20 scans tirés au hasard) |
| `verite_terrain.csv` | vérité terrain vérifiée à la main sur les images (20 factures × 14 champs) |
| `etape5_evaluation.py` | étape 5 : précision de l'OCR champ par champ, pour plusieurs résolutions |
