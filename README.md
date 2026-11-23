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
| 6 | `uv run python etape6_entrepot.py` | crée l'entrepôt DuckDB `data/entrepot.duckdb` (vues SQL sur le bronze et le silver) |
| 7 | `uv run python test_etape7_mcp.py` | teste le serveur MCP `etape7_mcp.py` : chaque outil + tentatives d'attaque (28 tests) |

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

### L'entrepôt (`data/entrepot.duckdb`)

Le fichier ne contient **que des vues** : les données restent dans les fichiers Parquet (un seul exemplaire).

| Vue | Fichiers lus |
|---|---|
| `bronze.documents` | `data/bronze/run_*.parquet` |
| `silver.factures` | `data/silver/factures.parquet` |
| `silver.lignes_facture` | `data/silver/lignes_facture.parquet` |
| `silver.quarantaine` | `data/silver/quarantaine.parquet` |

- Les vues contiennent le chemin des fichiers **sur votre machine** : le fichier n'est pas versionné, chacun le
  crée avec `uv run python etape6_entrepot.py` (à refaire seulement si le projet change de dossier).
- Les vues sont toujours à jour : inutile de recréer l'entrepôt quand le bronze ou le silver changent.
- **Toujours ouvrir l'entrepôt en lecture seule** : plusieurs lecteurs peuvent travailler en même temps, mais
  une seule connexion en lecture-écriture bloque tous les autres programmes.

Depuis Python :

```python
from etape6_entrepot import ouvrir_entrepot   # connexion en lecture seule
con = ouvrir_entrepot()
con.execute("SELECT sum(total_ttc) FROM silver.factures WHERE statut_paiement = 'En retard'").fetchall()
```

Depuis **DBeaver** :

1. *Nouvelle connexion* → **DuckDB** (DBeaver propose de télécharger le pilote la première fois).
2. *Path* : le chemin complet de `data/entrepot.duckdb`.
3. Onglet *Général* (ou *Paramètres de connexion*) : cocher **Lecture seule** (*Read-only connection*).
4. *Terminer*, puis ouvrir un éditeur SQL : `SELECT * FROM silver.factures;`

### Le serveur MCP (`etape7_mcp.py`)

| Outil | Rôle |
|---|---|
| `lister_factures` | liste des factures, filtres : fournisseur, client, statut de paiement, statut qualité, catégorie, période |
| `totaux_factures` | nombre et totaux HT / TVA / TTC avec les mêmes filtres, regroupement facultatif |
| `detail_facture` | une facture et ses lignes |
| `schema_donnees` | tables, colonnes, types et valeurs possibles des statuts |
| `requete_sql` | une requête `SELECT` libre (lecture seule) |

Chaque réponse contient `sql` : les requêtes réellement exécutées.

**Sécurité** : filtres passés en paramètres (`?`), une seule requête `SELECT` acceptée par `requete_sql`,
entrepôt ouvert en lecture seule, DuckDB limité aux dossiers `data/bronze` et `data/silver` (impossible de lire
`.env` ou d'écrire un fichier), configuration verrouillée.

**Utilisation avec Claude Code** : le fichier `.mcp.json` du projet déclare le serveur. Ouvrir une session Claude Code
dans ce dossier, accepter le serveur `factures`, puis poser une question (« Quel est le montant TTC des factures en
retard en 2025 ? »). `uv` doit être accessible dans le `PATH` de Claude Code.

**Utilisation avec Claude Desktop** : ajouter dans `claude_desktop_config.json` :

```json
{ "mcpServers": { "factures": { "command": "/chemin/vers/uv",
    "args": ["run", "--directory", "/chemin/vers/architecture-data-IA-securite", "python", "etape7_mcp.py"] } } }
```

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
| `etape6_entrepot.py` | étape 6 : entrepôt DuckDB (vues SQL) + `ouvrir_entrepot()` en lecture seule |
| `etape7_mcp.py` | étape 7 : serveur MCP (5 outils en lecture seule) |
| `test_etape7_mcp.py` | étape 7 : tests de chaque outil et des protections |
| `.mcp.json` | déclaration du serveur MCP pour Claude Code |
