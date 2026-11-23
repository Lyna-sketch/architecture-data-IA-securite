# De la facture scannée à l'agent IA

Chaîne complète et reproductible : des factures PDF (natives ou scannées) jusqu'à un agent IA qui répond en
français aux questions sur ces factures.

```
Bucket S3 ─► détection texte / image ─► OCR (LightOnOCR-3) ─► bronze ─► silver ─► entrepôt DuckDB ─► serveur MCP ─► agent IA
 étape 1           étape 1                 étape 2         étape 3   étape 4      étape 6          étape 7       étape 8
                                                    (étape 5 : mesure de la qualité de l'OCR)
```

---

## 1. Prérequis

- Linux ou macOS, avec un accès Internet.
- Les accès fournis par l'enseignant ou créés dans la console Hyperfluid :
  - une clé S3 pour le bucket `factures` ;
  - une clé d'API pour le modèle d'OCR `lightonocr-3-1b-test` ;
  - une clé d'API pour le LLM `gemma-4-12b` (agent).

## 2. Installation (une seule fois)

**1. Installer [uv](https://docs.astral.sh/uv/)**, qui installe Python et toutes les bibliothèques du projet :

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Ouvrez ensuite un nouveau terminal, ou chargez uv dans le terminal actuel :

```bash
source ~/.local/bin/env
```

**2. Installer les bibliothèques du projet** (versions figées par `uv.lock`) :

```bash
uv sync
```

**3. Créer le fichier de configuration**, puis le remplir (voir section 3) :

```bash
cp .env.example .env
```

## 3. Configuration (`.env`)

Le fichier `.env` contient les secrets. Il est ignoré par Git : ne le commitez jamais et ne le partagez pas.

| Variables | Valeur | Où la trouver |
|---|---|---|
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | clé S3 du bucket `factures` | fournie par l'enseignant |
| `AWS_ENDPOINT_URL`, `AWS_DEFAULT_REGION`, `S3_BUCKET` | déjà remplies dans `.env.example` | — |
| `OCR_API_KEY` | clé `sk-…` | console Hyperfluid, page du modèle d'OCR |
| `OCR_BASE_URL`, `OCR_MODEL` | `https://llm.hyperfluid.cloud/v1/organizations/<organisation>/shared-models/lightonocr-3-1b-test/v1` et `lightonocr-3-1b-test` | page du modèle dans la console Hyperfluid |
| `GEMMA_API_KEY` | clé `sk-…` | console Hyperfluid |
| `GEMMA_BASE_URL`, `GEMMA_MODEL` | même forme d'adresse que l'OCR, avec `gemma-4-12b` | page du modèle dans la console Hyperfluid |

`OCR_BASE_URL` est l'adresse de l'**API**, qui se termine par `/v1`, et non l'adresse de la page de la console.

---

## 4. Lancer le projet, étape par étape

Toutes les commandes se lancent **à la racine du projet**. Chaque étape utilise le résultat de la précédente :
suivez-les dans l'ordre.

### Étape 1 : récupérer les factures et les classer

```bash
uv run python etape1_recuperer.py
```

**Ce que vous devez voir :** les 100 factures téléchargées dans `data/landing/`, puis la liste des PDF avec leur
type, et pour finir `Total : 50 texte, 50 image, 0 erreur`.

**À essayer :** relancez la commande. Elle affiche `0 nouvelle(s) facture(s) téléchargée(s)` : seules les nouvelles
factures du bucket sont récupérées.

### Étape 2 : envoyer une page au modèle d'OCR

```bash
uv run python etape2_ocr.py facture_P-2025-0002_scan.pdf
```

**Ce que vous devez voir :** le texte de la facture en Markdown (avec les tableaux en HTML), puis la résolution et le
temps de traitement de la page (de 4 à 10 s environ).

**À essayer :** une autre résolution, en DPI (130 par défaut), par exemple 200, puis 50 :

```bash
uv run python etape2_ocr.py facture_P-2025-0002_scan.pdf 200
```

À 50 DPI, comparez au PDF : le modèle invente des valeurs plausibles (numéro, SIRET, nom du client).

### Étape 3 : construire la couche bronze

Pour un premier essai, on peut se limiter à 5 factures :

```bash
uv run python etape3_bronze.py 5
```

Puis on traite toutes les autres :

```bash
uv run python etape3_bronze.py
```

**Ce que vous devez voir :** une ligne par PDF, avec la méthode (`pypdf` ou `ocr`), le statut et la durée. Les 50 scans
passent par l'OCR (environ 7 minutes en tout), et les PDF texte sont lus en quelques millisecondes.

**À essayer (critères de l'énoncé) :**

1. **Rien n'est retraité.** Relancez `uv run python etape3_bronze.py`. Résultat attendu : `0 PDF à traiter. Rien de nouveau : aucun appel OCR.`
2. **Une panne de l'OCR ne fait pas planter le pipeline.** Ajoutez une facture modifiée, puis lancez le script avec une fausse adresse d'OCR (elle ne vaut que pour cette commande) :

   ```bash
   cp data/landing/facture_A-2025-0003_scan.pdf data/landing/test_panne.pdf && echo " " >> data/landing/test_panne.pdf
   ```

   ```bash
   OCR_BASE_URL=https://ocr-en-panne.invalid/v1 uv run python etape3_bronze.py
   ```

   Résultat attendu : `0 ok, 1 erreur(s)`, sans plantage. Relancez normalement `uv run python etape3_bronze.py` : le fichier est retraité et passe en `ok`.
   Supprimez ensuite le fichier de test avec `rm data/landing/test_panne.pdf`. Ses lignes restent dans le bronze, qui n'est jamais modifié.

### Étape 4 : construire la couche silver

```bash
uv run python etape4_silver.py
```

**Ce que vous devez voir :** `100 factures en silver (99 valides, 1 signalées)`, `271 lignes de facture`, et la facture
signalée `V-2025-0001`, dont le TTC (99 999,99 €) ne correspond pas à HT + TVA.

Si vous avez fait l'essai de l'étape 3, `test_panne.pdf` apparaît aussi en quarantaine avec le motif
`doublon : facture A-2025-0003 de Aubry déjà présente`. C'est la preuve qu'aucun doublon ne passe.

**À essayer :** afficher une facture et la comparer à son PDF :

```bash
uv run python -c "import pandas as pd; f = pd.read_parquet('data/silver/factures.parquet'); print(f[f.numero_facture == 'P-2025-0002'].T)"
```

### Étape 5 : mesurer la qualité de l'OCR

```bash
uv run python etape5_evaluation.py
```

**Ce que vous devez voir :** le tableau de précision par champ, comparé à la vérité terrain `verite_terrain.csv`
(20 factures × 14 champs vérifiés à la main), à 50, 72, 130 et 200 DPI. On attend 100 % dès 72 DPI et 85,7 % à 50 DPI,
puis le détail des erreurs.

Le premier lancement fait 80 appels OCR (environ 10 minutes) ; les suivants réutilisent les textes gardés dans
`data/evaluation/`. On peut tester d'autres résolutions : `uv run python etape5_evaluation.py 100 300`.

### Étape 6 : créer l'entrepôt SQL

```bash
uv run python etape6_entrepot.py
```

**Ce que vous devez voir :** `Entrepôt créé : data/entrepot.duckdb`, puis le nombre de lignes de chaque vue
(`silver.factures` : 100 lignes).

**À essayer :**

- **Une requête SQL depuis Python** (réponse attendue : 12 factures, 106 886,43 €) :

  ```bash
  uv run python -c "from etape6_entrepot import ouvrir_entrepot; print(ouvrir_entrepot().execute(\"SELECT count(*), sum(total_ttc) FROM silver.factures WHERE statut_paiement = 'En retard' AND year(date_emission) = 2025\").fetchall())"
  ```

- **Depuis DBeaver** :
  1. Créez une *Nouvelle connexion* → **DuckDB**.
  2. Dans *Path*, indiquez le chemin complet de `data/entrepot.duckdb`.
  3. Cochez **Lecture seule** (*Read-only connection*).
  4. Ouvrez un éditeur SQL et lancez `SELECT * FROM silver.factures;`.

  Laissez DBeaver ouvert et relancez `uv run python etape4_silver.py` : le pipeline n'est pas bloqué.

### Étape 7 : tester le serveur MCP

```bash
uv run python test_etape7_mcp.py
```

**Ce que vous devez voir :** chaque outil appelé et vérifié, puis 10 tentatives d'attaque toutes refusées
(`DELETE`, `DROP`, lecture du `.env`, injection SQL…), et pour finir `29/29 tests réussis`.

**À essayer avec Claude Code :** ouvrez une session Claude Code dans ce dossier. Le fichier `.mcp.json` y déclare le
serveur `factures` : acceptez-le quand Claude Code le demande. Posez ensuite la question :
*« Quel est le montant TTC des factures en retard en 2025 ? »* Claude Code appelle `totaux_factures` et répond 106 886,43 €.

### Étape 8 : discuter avec l'agent

```bash
uv run python etape8_agent.py
```

**Ce que vous devez voir :** `Agent factures — LLM : gemma-4-12b`, puis une invite `Vous >`. Pour chaque question,
l'agent affiche les outils appelés (🔧), les requêtes SQL et les résultats, puis sa réponse.

**Questions à essayer :**

- *Quel est le montant TTC des factures en retard en 2025 ?* (réponse attendue : 106 886,43 €)
- *Quel fournisseur a le plus gros montant total TTC ?* puis *Et combien de factures a-t-il émises ?* : l'agent garde le fil.
- *Y a-t-il des factures suspectes ? Pourquoi ?*
- *Donne-moi le détail de la facture P-2025-0002.*

Tapez `quitter` (ou Ctrl+D) pour arrêter l'agent.

**Poser une seule question :**

```bash
uv run python etape8_agent.py -q "Quel est le montant TTC des factures en retard en 2025 ?"
```

**Changer de LLM sans toucher au code :** décrivez un autre profil dans `.env`, puis choisissez-le avec `--llm`.
Par exemple, pour un modèle local avec [Ollama](https://ollama.com) (`ollama pull qwen2.5:7b`), le profil `ollama`
est déjà prévu dans `.env.example` :

```bash
uv run python etape8_agent.py --llm ollama
```

---

## 5. Repartir de zéro

Les données produites sont dans `data/`, qui n'est pas versionné. Pour tout reconstruire, supprimez les couches
puis relancez les étapes 3 à 6. Cela refait les 50 appels OCR du bronze.

```bash
rm -r data/bronze data/silver data/entrepot.duckdb
```

---

## 6. Référence technique

### Couche bronze (`data/bronze/run_*.parquet`)

- Chaque exécution **ajoute** un fichier ; les précédents ne sont jamais modifiés.
- Un document est reconnu par l'**empreinte sha256** de son contenu, et non par son nom.
- Une erreur d'OCR (service indisponible, réponse vide) est enregistrée avec `statut = erreur`, puis retentée au lancement suivant.
- Colonnes : `sha256`, `nom_fichier`, `taille_octets`, `nb_pages`, `type_pdf`, `methode`, `modele_ocr`, `ocr_dpi`,
  `texte`, `duree_s`, `date_ingestion`, `statut`, `erreur`.

### Couche silver (`data/silver/`)

| Fichier | Contenu |
|---|---|
| `factures.parquet` | une ligne par facture, avec `statut_qualite` (`valide` / `signalee`) et `anomalies` |
| `lignes_facture.parquet` | une ligne par ligne de facture |
| `quarantaine.parquet` | documents rejetés, avec leur `motif` |

- Montants en `decimal(12,2)`, dates en `date`. Le silver est recalculé entièrement à partir du bronze.
- **Rejetée** : champ obligatoire manquant ou illisible, date invalide, doublon (même fournisseur et même numéro).
- **Signalée** : HT + TVA ≠ TTC, somme des lignes ≠ HT, quantité × prix ≠ total de ligne, échéance avant émission, SIRET invalide.

### Entrepôt (`data/entrepot.duckdb`)

Le fichier ne contient que 4 vues (`bronze.documents`, `silver.factures`, `silver.lignes_facture`,
`silver.quarantaine`) qui lisent les fichiers Parquet : les données n'existent qu'en un seul exemplaire.

- Les vues contiennent les chemins de **votre** machine : le fichier n'est pas versionné, chacun le crée avec l'étape 6.
- **Ouvrez toujours l'entrepôt en lecture seule** : un seul programme en lecture-écriture bloque tous les autres.

### Serveur MCP (`etape7_mcp.py`)

| Outil | Rôle |
|---|---|
| `lister_factures` | liste des factures ; filtres : fournisseur, client, statut de paiement, statut qualité, catégorie, période |
| `totaux_factures` | nombre et totaux HT / TVA / TTC avec les mêmes filtres, regroupement facultatif |
| `detail_facture` | une facture et ses lignes |
| `schema_donnees` | tables, colonnes, types et valeurs possibles des statuts |
| `requete_sql` | une requête `SELECT` libre |

Chaque réponse contient `sql` : les requêtes réellement exécutées.

La sécurité repose sur quatre protections :
- les filtres sont passés en paramètres (`?`) ;
- `requete_sql` n'accepte qu'un seul `SELECT` ;
- l'entrepôt est ouvert en lecture seule ;
- DuckDB ne peut lire que `data/bronze` et `data/silver`, et cette configuration est verrouillée.

Pour l'utiliser avec **Claude Desktop**, ajoutez ceci dans `claude_desktop_config.json` :

```json
{ "mcpServers": { "factures": { "command": "/chemin/vers/uv",
    "args": ["run", "--directory", "/chemin/vers/architecture-data-IA-securite", "python", "etape7_mcp.py"] } } }
```

### Agent (`etape8_agent.py`)

- **Le LLM se choisit dans la configuration.** Un profil `P` est décrit dans `.env` par `P_BASE_URL`, `P_API_KEY` et
  `P_MODEL`, ce qui fonctionne avec toute API compatible OpenAI (Hyperfluid/vLLM, Ollama, OpenAI, Anthropic…). Le profil
  par défaut est donné par `LLM_PROFIL`, et `--llm` permet d'en choisir un autre.
- L'agent n'accède aux données **que** par les outils MCP, et il affiche chaque outil appelé, le SQL et le résultat.
- Sa consigne lui interdit tout chiffre qui ne vient pas d'un outil, et les sommes sont calculées par la base.

## 7. Fichiers du projet

| Fichier | Rôle |
|---|---|
| `config.py` | configuration commune (lit `.env`) |
| `etape1_recuperer.py` | étape 1 : téléchargement S3 et détection texte / image |
| `etape2_ocr.py` | étape 2 : appel du modèle LightOnOCR-3 |
| `etape3_bronze.py` | étape 3 : couche bronze (texte brut, traçabilité, incrémental) |
| `etape4_silver.py` | étape 4 : couche silver (parsing, typage, contrôles qualité, quarantaine) |
| `etape5_verite_terrain.py` | étape 5 : prépare le brouillon de vérité terrain |
| `verite_terrain.csv` | vérité terrain vérifiée à la main (20 factures × 14 champs) |
| `etape5_evaluation.py` | étape 5 : précision de l'OCR champ par champ |
| `etape6_entrepot.py` | étape 6 : entrepôt DuckDB et `ouvrir_entrepot()` en lecture seule |
| `etape7_mcp.py` | étape 7 : serveur MCP |
| `test_etape7_mcp.py` | étape 7 : tests des outils et des protections |
| `.mcp.json` | déclaration du serveur MCP pour Claude Code |
| `etape8_agent.py` | étape 8 : agent IA |
| `.env.example` | modèle de configuration, sans secrets |
