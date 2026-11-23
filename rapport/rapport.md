# De la facture scannée à l'agent IA : rapport de projet
 
**Auteurs :** [noms du groupe]
**Date :** novembre 2026
 
---
 
## 1. Introduction et état d'avancement
 
L'objectif du projet est de construire, de bout en bout et de façon reproductible, une chaîne qui récupère des factures PDF (natives ou scannées), en extrait les informations, les stocke proprement et permet de les interroger en langage naturel :
 
```
PDF (S3) ──► extraction / OCR ──► bronze ──► silver ──► entrepôt ──► serveur MCP ──► agent IA
 étape 1        étapes 2-3         étape 3    étape 4    étape 6       étape 7        étape 8
```
 
| Étape | Contenu | État |
|---|---|---|
| 1 | Récupération des factures et détection texte / image | Réalisée |
| 2 | Appel du modèle d'OCR LightOnOCR-3 | Réalisée |
| 3 | Couche bronze (incrémentale, traçable) | Réalisée |
| 4 | Couche silver (typée, contrôlée) | Réalisée |
| 5 | Mesure de la qualité de l'OCR | Réalisée |
| 6 | Entrepôt de données SQL (DuckDB) | Réalisée |
| 7 | Serveur MCP | **En cours** |
| 8 | Agent IA | **À venir** |
| 9 | Industrialisation | Proposition rédigée (section 9) |
 
Nous avons avancé étape par étape, en validant chacune avant de passer à la suivante. Les étapes 1 à 6 sont réalisées et testées ; les étapes 7 et 8 sont en cours (section 8).
 
---
 
## 2. Choix techniques et justifications
 
| Brique | Choix | Justification |
|---|---|---|
| Langage et environnement | Python, gestionnaire `uv` avec fichier de verrouillage `uv.lock` | Écosystème riche pour les PDF et les données ; dépendances figées, donc exécution identique d'une machine à l'autre. |
| Détection texte / image | Comptage des caractères extraits avec `pypdf` (seuil : plus de 20 caractères = texte) | Simple, rapide et sans appel réseau. Un scan ne contient aucune couche texte, donc un nombre de caractères quasi nul. |
| OCR | LightOnOCR-3 (imposé), appelé via une API de type « OpenAI chat completions » | Contrainte de l'énoncé. Le fournisseur est isolé dans une seule fonction, `appeler_ocr(image_png)`. |
| Résolution d'image | 130 DPI | Voir section 4 : respecte la recommandation du modèle et garde une marge de sécurité. |
| Identification des fichiers | Empreinte `sha256` du contenu | Détecte les fichiers déjà vus indépendamment de leur nom (section 5). |
| Stockage bronze et silver | Fichiers Parquet | Format colonne typé (dates, décimaux), compact, lisible par pandas et par les moteurs SQL comme DuckDB. Un fichier par exécution pour le bronze, donc jamais de réécriture. |
| Entrepôt SQL | DuckDB, fichier `entrepot.duckdb` ne contenant que des vues sur les fichiers Parquet | Moteur SQL analytique embarqué (aucun serveur à installer), qui lit le Parquet directement : les données restent en un seul exemplaire, ce qui sépare stockage et calcul. Accessible depuis Python et depuis DBeaver (section 8.1). |
| Montants | `decimal128(12, 2)` | Un flottant ne représente pas exactement les centimes (erreurs d'arrondi binaire), ce qui fausserait les sommes et les contrôles HT + TVA = TTC. |
| Secrets | Fichier `.env` ignoré par Git, modèle `.env.example` sans valeurs | Aucune clé dans le dépôt. Suffisant pour un projet, insuffisant pour la production (section 9). |
 
---
 
## 3. Étape 1 : récupérer les factures
 
Le script `etape1_recuperer.py` télécharge depuis le bucket S3 les factures qui ne sont pas encore présentes dans la zone d'arrivée (`data/landing/`), puis classe chaque fichier. Les identifiants d'accès sont lus dans le `.env`.
 
**Résultat :** 100 factures téléchargées, soit **50 « texte » et 50 « image »**, avec 0 erreur.
 
**Méthode de classification.** Nous comptons les caractères extraits de chaque PDF : au-delà de 20 caractères, le fichier est classé « texte » ; sinon il est classé « image » et passera par l'OCR. Le seuil évite de classer comme texte un scan qui contiendrait quelques caractères parasites. La répartition obtenue correspond d'ailleurs aux suffixes `_texte` et `_scan` des noms de fichiers.
 
---
 
## 4. Étape 2 : appeler le modèle d'OCR
 
La clé d'API est créée sur la console Hyperfluid et stockée dans le `.env`. Le script `etape2_ocr.py` convertit une page en image PNG, l'envoie au modèle et affiche le texte reconnu ainsi que le temps de traitement.
 
**Format de sortie.** Le modèle renvoie du Markdown : titres (`# FACTURE`), texte en gras pour les libellés, séparateurs `---`, et **tableaux en HTML** (`<table>`, `<tr>`, `<td>`). Exemple sur la facture `P-2025-0002` : les quatre lignes d'articles sont rendues en `<table>`, suivies des totaux HT, TVA et TTC en texte.
 
### Questions de l'énoncé
 
**Quel format de requête le modèle attend-il ?**
Une requête au format « OpenAI chat completions » ne contenant que l'image en PNG base64, avec `temperature = 0.2`, `top_p = 0.9` et `max_tokens = 4096` (c'est ce que fait `appeler_ocr()`). Il n'accepte aucune consigne texte, hormis un prompt vide pour transcrire ou `"grounding"` pour obtenir les coordonnées des blocs. Nous avons testé l'ajout d'une instruction demandant le Total TTC en JSON : le modèle l'a ignorée et a renvoyé toute la page avec des coordonnées spatiales et des lignes fusionnées. C'est un moteur de transcription, pas un modèle conversationnel.
 
**Quelle résolution, et que se passe-t-il si on ne la respecte pas ?**
La documentation recommande au maximum 1540 pixels sur le grand côté, soit environ 130 DPI sur une page A4. Mesures sur une même page de test (19 valeurs à retrouver) :
 
| Résolution | Poids de l'image | Temps OCR | Valeurs correctes |
|---|---|---|---|
| 40 DPI | 105 Ko | 8,4 s | 1 / 19 |
| 50 DPI | 171 Ko | 6,4 s | 14 / 19 |
| 72 DPI | 374 Ko | 6,2 s | 19 / 19 |
| 100 DPI | 760 Ko | 6,8 s | 19 / 19 |
| 130 DPI | 1,2 Mo | 7,7 s | 19 / 19 |
| 200 DPI | 2,6 Mo | 10,0 s | 19 / 19 |
| 300 DPI | 4,0 Mo | 12,1 s | 19 / 19 |
 
Les temps varient avec la charge du service : lors d'une autre série de mesures, la même page prenait 3,5 à 3,6 s à 130 DPI et 3,9 à 4,3 s à 200 DPI.
 
**Quel compromis entre taille, vitesse et qualité ?**
En dessous de 72 DPI, la qualité s'effondre. Au-dessus de 130 DPI, on ne gagne rien en précision mais le coût augmente : à 300 DPI, le temps est supérieur de 57 % (12,1 s contre 7,7 s) et le poids 3,4 fois plus élevé. Sur 100 pages, cela représente environ 7 minutes de plus, un écart qui compte à grande échelle (étape 9). Nous avons retenu **130 DPI** : cela respecte la recommandation du constructeur (environ 1521 px) et laisse une marge de sécurité pour de vrais scans flous ou penchés.
 
**Notre code doit-il dépendre du fournisseur d'OCR ?**
Non. Le fournisseur est isolé dans l'unique fonction `appeler_ocr(image_png)`, appelée par `etape3_bronze.py` sans qu'il en connaisse le fonctionnement. Pour passer à un autre modèle compatible, il suffit de modifier `OCR_BASE_URL` et `OCR_MODEL` dans le `.env`. Pour changer totalement de moteur, il suffit de réécrire cette fonction. La colonne `modele_ocr` de la table bronze garde la trace du moteur utilisé pour chaque document.
 
**Où stocker la clé d'API ?**
Dans le fichier local `.env`, ignoré par Git via le `.gitignore`. Le dépôt ne contient que `.env.example`, avec des valeurs vides.
 
---
 
## 5. Étape 3 : couche bronze
 
Le script `etape3_bronze.py` parcourt `data/landing/`. Pour chaque PDF, il calcule l'empreinte `sha256`, lit le texte avec `pypdf` si le fichier est de type texte, ou passe par l'OCR s'il s'agit d'un scan. Le résultat est écrit dans un nouveau fichier Parquet par exécution (`data/bronze/run_<date>.parquet`), sans jamais modifier les précédents.
 
**Métadonnées conservées :**
 
| Colonnes | Ce qu'elles disent |
|---|---|
| `nom_fichier`, `sha256`, `taille_octets` | Quel fichier exactement |
| `type_pdf`, `methode` | Texte ou scan ; lu avec pypdf ou par OCR |
| `modele_ocr`, `ocr_dpi` | Avec quel modèle et quel réglage (utile pour comparer à l'étape 5) |
| `date_ingestion`, `duree_s` | Quand et en combien de temps |
| `statut`, `erreur` | Si cela a marché et, sinon, pourquoi |
 
### Tests réalisés
 
**Test 1 : relancer le pipeline.** La seconde exécution affiche « 0 PDF à traiter. Rien de nouveau : aucun appel OCR. » Au démarrage, le script lit tout le bronze et construit `deja_ok`, l'ensemble des empreintes déjà traitées avec succès. Les 100 empreintes y figurent, donc la liste à traiter est vide.
 
**Test 2 : traçabilité et historique.** Le bronze contient 102 lignes pour 100 factures : 100 lignes `ok` et 2 lignes `erreur` issues de la panne simulée. Les lignes d'erreur ne sont pas effacées : le bronze garde l'historique de tout ce qui s'est passé.
 
**Test 3 : copie renommée.** Une copie d'un PDF sous un autre nom n'est pas retraitée : le script reconnaît un fichier à son contenu, pas à son nom. Mêmes octets, donc même empreinte, déjà présente dans `deja_ok`.
 
**Test 4 : fichier modifié et service OCR en panne.** Nous avons créé `facture_modifiee.pdf` en ajoutant un espace à la fin d'une copie de `facture_A-2025-0003_scan.pdf`, puis lancé le script avec une fausse adresse d'OCR (`OCR_BASE_URL=https://ocr-en-panne.invalid/v1`, valable pour cette commande seulement). Résultat : le fichier est traité (empreinte différente), l'appel échoue, le pipeline **ne plante pas** et affiche « 0 ok, 1 erreur(s) », avec une ligne `statut = erreur` écrite dans un nouveau fichier `run_…parquet`. Au lancement suivant, le fichier est retenté, car `deja_ok` ne contient que les empreintes au statut `ok`. Les anciens fichiers Parquet ne sont jamais modifiés, et une exécution sans rien à faire n'en crée pas.
 
Le contenu de `facture_modifiee.pdf` reste la facture A-2025-0003. Le bronze ne détecte pas ce type de doublon fonctionnel : ce n'est pas son rôle, c'est celui du silver, qui compare les numéros de facture.
 
### Questions de l'énoncé
 
**Comment reconnaître qu'un fichier a déjà été vu ? Le nom suffit-il ?**
Par l'empreinte `sha256` du contenu. Le nom ne suffit pas : un même fichier peut arriver sous deux noms (traité deux fois), et un fichier corrigé peut garder son nom (nouvelle version ratée).
 
**Quelles métadonnées garder ?**
Celles du tableau ci-dessus : quel fichier, comment il a été lu, avec quel modèle et quel réglage, quand, et avec quel résultat.
 
**Pourquoi ne jamais modifier ni supprimer le bronze ?**
C'est la seule trace de ce que l'OCR a réellement lu. On peut toujours reconstruire le silver à partir de lui sans refaire l'OCR, et auditer une valeur douteuse en revenant au texte d'origine. Si on le modifiait, on ne pourrait plus distinguer une erreur de l'OCR d'une erreur de notre propre traitement.
 
---
 
## 6. Étape 4 : couche silver
 
Le script `etape4_silver.py` transforme le texte brut du bronze en deux tables Parquet : `factures.parquet` (une ligne par facture) et les lignes de facture. Il applique des contrôles de qualité, attribue à chaque facture un `statut_qualite` et écrit les documents écartés dans une table de quarantaine.
 
**Schéma de la table des factures :** `numero_facture`, `fournisseur`, `siret_fournisseur`, `client`, `siret_client` (texte) ; `date_emission`, `date_echeance` (`date32`) ; `categorie`, `statut_paiement`, `mode_paiement` (texte) ; `total_ht`, `total_tva`, `total_ttc` (`decimal128(12, 2)`) ; `nb_lignes` (`int32`) ; `statut_qualite`, `anomalies` ; et la traçabilité `source_sha256`, `source_fichier`, `methode_extraction`.
 
### Résultats
 
- 100 documents lus dans le bronze, **100 factures en silver** (99 valides, 1 signalée) et **271 lignes de facture**, 0 document en quarantaine.
- **Aucune perte, aucun doublon :** 100 factures, 100 numéros distincts, 0 champ vide (hors colonne `anomalies`).
- **Types corrects :** dates en `date32`, montants en `decimal128(12, 2)`.
- **Vérification sur un cas réel :** la facture `P-2025-0002` (OCR) donne en silver total HT 15 897,98 €, TVA 3 179,60 €, TTC 19 077,58 € et 4 lignes, identiques au PDF.
- **Incohérence détectée :** la facture `V-2025-0001` est signalée avec l'anomalie « HT + TVA (177.91) != TTC (99999.99) ».
### Questions de l'énoncé
 
**Quel type pour des montants en euros ?**
Un décimal à précision fixe (`decimal128(12, 2)`), pas un flottant : les flottants ne représentent pas exactement la plupart des valeurs à deux décimales, ce qui provoque des écarts d'arrondi dans les sommes et fausserait le contrôle HT + TVA = TTC.
 
**Comment écrire un parseur robuste aux variations entre texte OCR et PDF natif ?**
Le texte OCR est du Markdown avec des tableaux HTML, alors que le texte extrait d'un PDF natif a une autre forme. Le parseur doit donc extraire les champs sans dépendre de la mise en forme exacte (espaces dans les montants comme « 1 263,00 € », virgule décimale, dates `jj/mm/aaaa`). [À compléter : décrire les choix précis du parseur, par exemple expressions régulières par champ et normalisation des montants.]
 
**Si l'OCR lit mal un montant, faut-il le corriger automatiquement ?**
Non. Corriger sans vérifier masque l'erreur que l'on cherche justement à voir, et on ne saurait plus si la valeur vient du document ou de notre correction. Nous signalons l'incohérence (statut `signalee` et motif dans `anomalies`) pour qu'un humain tranche.
 
**Quelle différence entre une facture rejetée et une facture signalée ?**
Une facture *rejetée* est inexploitable : elle est écartée du silver et placée en quarantaine avec un motif. Une facture *signalée* reste dans le silver avec un statut de qualité et la liste de ses anomalies, car l'information est présente mais suspecte, comme la facture `V-2025-0001`.
 
---
 
## 7. Étape 5 : mesurer la qualité de l'OCR
 
**Vérité terrain.** Elle porte sur 20 factures scannées × 14 champs = **280 valeurs**. Nous avons pré-rempli les valeurs avec l'extraction, puis vérifié chacune sur l'image. Aucune n'a dû être corrigée.
 
**Méthode.** `etape5_evaluation.py` compare le silver à la vérité terrain champ par champ, pour quatre résolutions (50, 72, 130 et 200 DPI). Les résultats sont enregistrés dans `data/evaluation/`.
 
### Précision par champ (% de valeurs exactes)
 
| Champ | 50 DPI | 72 DPI | 130 DPI | 200 DPI |
|---|---|---|---|---|
| numero_facture | 75,0 | 100 | 100 | 100 |
| fournisseur | 100 | 100 | 100 | 100 |
| siret_fournisseur | 55,0 | 100 | 100 | 100 |
| client | 50,0 | 100 | 100 | 100 |
| siret_client | 85,0 | 100 | 100 | 100 |
| date_emission | 95,0 | 100 | 100 | 100 |
| date_echeance | 85,0 | 100 | 100 | 100 |
| categorie | 85,0 | 100 | 100 | 100 |
| statut_paiement | 100 | 100 | 100 | 100 |
| mode_paiement | 90,0 | 100 | 100 | 100 |
| total_ht | 95,0 | 100 | 100 | 100 |
| total_tva | 100 | 100 | 100 | 100 |
| total_ttc | 95,0 | 100 | 100 | 100 |
| nb_lignes | 90,0 | 100 | 100 | 100 |
| **Tous les champs** | **85,7** | **100** | **100** | **100** |
 
Le temps OCR moyen par page n'apparaît pas dans cette exécution, car les résultats provenaient du cache ; les temps mesurés sont ceux de l'étape 2.
 
### Analyse : quels champs sont les plus fragiles ?
 
À 72 DPI et au-delà, tout est exact. À 50 DPI, les champs les plus fragiles sont :
 
- **`client` (50 %) et `siret_fournisseur` (55 %)** : les noms propres, qu'aucun contexte ne permet de deviner (« Fleury » lu « Finruy », « Mace S.A. » lu « Mirex S.A. »), et les longues suites de 14 chiffres, où un seul chiffre mal lu rend la valeur fausse (chiffres sautés ou confondus, comme 8 lu 6 ou 5).
- **`numero_facture` (75 %)** : un chiffre mal lu change l'identifiant (« A-2025-0004 » lu « A-2038-0004 », ou « P-2025-0002 » lu « P-2625-0002 »).
- **Les dates et les montants** sont rarement touchés (85 à 100 %) mais restent dangereux, car une erreur d'un chiffre est plausible (échéance « 2025-08-12 » lue « 2025-06-12 »).
Les erreurs viennent donc surtout des chaînes de chiffres et des noms propres, là où l'image dégradée supprime la redondance qui aide à lire.
 
### Questions de l'énoncé
 
**Comment obtenir une vérité terrain fiable sans y passer des heures ?**
On pré-remplit avec les valeurs extraites, puis un humain vérifie chaque valeur sur l'image : vérifier est bien plus rapide que tout saisir. Le risque est un biais de confirmation (section 10).
 
**Quelle taille d'échantillon ?**
Avec 20 factures, chaque champ n'a que 20 valeurs, donc une seule erreur pèse 5 %. C'est suffisant pour voir des écarts nets (100 % contre 50 %), mais pas pour mesurer un taux d'erreur rare. Pour cela, il faudrait plusieurs centaines de factures, avec des scans plus abîmés.
 
---
 
## 8. Étapes 6, 7 et 8 : entrepôt, serveur MCP et agent
 
### 8.1 Étape 6 : l'entrepôt de données
 
Le script `etape6_entrepot.py` crée le fichier `data/entrepot.duckdb`. Ce fichier ne contient **aucune donnée**, seulement quatre **vues**, c'est-à-dire des requêtes enregistrées qui lisent les fichiers Parquet au moment où on les interroge :
 
| Vue | Fichiers lus | Lignes |
|---|---|---|
| `bronze.documents` | `data/bronze/run_*.parquet` | 103 |
| `silver.factures` | `data/silver/factures.parquet` | 100 |
| `silver.lignes_facture` | `data/silver/lignes_facture.parquet` | 271 |
| `silver.quarantaine` | `data/silver/quarantaine.parquet` | 0 |
 
Les programmes s'y connectent par la fonction `ouvrir_entrepot()`, qui ouvre l'entrepôt **en lecture seule**. DBeaver s'y connecte avec le pilote DuckDB, en cochant l'option « lecture seule ».
 
**Résultats des tests :**
 
| Test | Résultat |
|---|---|
| Question de l'énoncé en SQL depuis Python : montant TTC des factures en retard émises en 2025 | 12 factures, **106 886,43 €** |
| Types conservés par DuckDB | `DATE` pour les dates, `DECIMAL(12,2)` pour les montants |
| Deux programmes ouvrent l'entrepôt en lecture seule en même temps | Les deux lisent normalement |
| Un programme ouvre l'entrepôt en lecture-écriture, un second essaie de lire | Le second est **bloqué** (« Could not set lock on file ») |
| Régénération du silver pendant qu'un lecteur tient l'entrepôt ouvert | Fonctionne : les données sont dans les Parquet, pas dans le fichier DuckDB |
| Consultation depuis DBeaver | [À compléter : capture d'écran de DBeaver connecté en lecture seule, avec une requête sur `silver.factures`] |
 
#### Questions de l'énoncé
 
**Comment séparer stockage et calcul ?**
Les données n'existent qu'une fois, dans les fichiers Parquet (le stockage). DuckDB ne fait que les lire au moment de la requête (le calcul). Les vues sont donc toujours à jour : quand le pipeline réécrit le silver, il n'y a rien à recharger dans l'entrepôt.
 
**Que se passe-t-il si plusieurs programmes accèdent aux mêmes données en même temps ?**
DuckDB accepte plusieurs lecteurs simultanés, mais un seul programme en écriture, qui bloque alors tous les autres. Nos tests le confirment. D'où notre règle : tout le monde ouvre l'entrepôt en lecture seule. C'est le cas de nos programmes (`ouvrir_entrepot()`), et il faut cocher l'option dans DBeaver. Ainsi, consulter l'entrepôt depuis un outil graphique n'empêche pas le reste du système de fonctionner.
 
**Comment les références aux fichiers restent-elles valides sur une autre machine ?**
Les vues contiennent le chemin complet des fichiers Parquet sur la machine où elles ont été créées. Le fichier `entrepot.duckdb` n'est donc pas versionné : chacun le recrée avec la commande `uv run python etape6_entrepot.py`, qui écrit les chemins de sa propre machine. Dans un conteneur, la même commande est lancée au démarrage. Seuls les Parquet et le script voyagent, jamais le fichier DuckDB.
 
### 8.2 Étape 7 : le serveur MCP
 
[À venir]
 
### 8.3 Étape 8 : l'agent
 
[À venir]
 
---
 
## 9. Étape 9 : industrialisation
 
**Point de départ.** Notre chaîne tourne aujourd'hui sur un poste, lancée à la main, script après script. Pour la passer en production avec des milliers de factures par mois et plusieurs utilisateurs, nous n'avons pas voulu tout traiter à la fois. Nous avons gardé les sujets qui nous paraissent les plus risqués, dans cet ordre : l'automatisation, la sécurité des secrets et des accès, la montée en charge de l'OCR, puis la supervision. Les tests et les coûts viennent ensuite.
 
### 9.1 Automatiser sans casser ce qui marche déjà
 
Notre meilleur atout est l'étape 3 : le pipeline est déjà *idempotent*. Une facture est reconnue par son empreinte `sha256`, donc relancer le traitement n'ajoute rien et ne refait aucun appel OCR. Les erreurs sont écrites dans le bronze avec `statut = erreur` et sont retentées au passage suivant. On peut donc automatiser sans risque : si un lancement plante à moitié ou se déclenche deux fois, on ne crée ni doublon ni perte.
 
Nous proposons de faire tourner `etape1 → etape3 → etape4` à intervalle régulier (toutes les nuits, ou toutes les heures si les factures arrivent en continu). Un simple cron dans un conteneur suffit pour démarrer. Un orchestrateur comme Airflow ou Dagster ne devient utile que si le nombre de chaînes augmente ou si l'on a besoin de relances et de dépendances visuelles ; pour un seul flux, ce serait trop lourd. Le tout serait packagé dans une image Docker avec les dépendances figées (le `uv.lock` nous aide déjà), pour que le traitement soit identique chez nous, sur un serveur ou chez un collègue.
 
### 9.2 Sécurité des accès et des secrets
 
Actuellement, les clés (S3, API d'OCR) vivent dans un fichier `.env` ignoré par Git. C'est correct pour un projet, pas pour la production. Nous les placerions dans un gestionnaire de secrets (Vault, ou celui du cloud utilisé), injectés au démarrage du conteneur, et jamais présentes dans l'image ni dans le dépôt. Nous y ajouterions :
 
- des clés distinctes par environnement et par service, avec le minimum de droits (lecture seule sur le bucket de factures, par exemple) et une rotation régulière ;
- pour le futur serveur MCP, un compte de base de données en lecture seule en plus de la vérification des requêtes, pour que même une injection SQL venue du LLM ne puisse rien modifier ;
- une authentification des utilisateurs de l'agent et une journalisation de qui a posé quelle question : les factures sont des données d'entreprise, et la traçabilité compte autant que le blocage.
### 9.3 Montée en charge de l'OCR
 
C'est le seul vrai goulot d'étranglement. D'après nos mesures, une page prend entre 3,5 et 7,7 s à 130 DPI selon la charge du service. Pour notre jeu de 100 factures, dont 50 scans (environ 50 pages), cela représente de 3 à 6,5 minutes de traitement, ce qui est négligeable. Le problème apparaîtrait avec la croissance : à 1 000 factures par mois (environ 500 pages à OCRiser), on serait entre 30 minutes et 1 heure en séquentiel, et bien plus lors d'un pic (clôture de fin d'année, rattrapage d'un arriéré).
 
Nous proposerions alors de traiter plusieurs pages en parallèle avec une file de tâches et plusieurs workers, en limitant le débit pour ne pas saturer le service d'OCR, avec des relances espacées en cas d'échec. Nos mesures donnent un garde-fou : rester à 130 DPI. En dessous de 72 DPI, la qualité s'effondre (85,7 % de valeurs exactes à 50 DPI) ; au-dessus de 130 DPI, on paie du temps et du poids sans gagner en précision. L'isolation du fournisseur dans `appeler_ocr()` nous permettrait de changer de modèle, ou d'héberger le nôtre, si le coût l'exigeait.
 
### 9.4 Supervision et gestion des erreurs
 
En production, une panne silencieuse est pire qu'une panne bruyante. Nous suivrions quelques indicateurs simples, issus de ce que nos tables contiennent déjà : nombre de factures ingérées par jour, proportion d'erreurs OCR, nombre de factures en quarantaine ou signalées, durée moyenne par page. Une alerte se déclencherait si le taux d'erreur monte ou si rien n'est ingéré pendant un jour ouvré. Les factures signalées (comme notre `V-2025-0001`, dont le TTC de 99 999,99 € ne correspond pas à HT + TVA) iraient dans une file de revue humaine plutôt que d'être corrigées automatiquement.
 
### 9.5 Tests et coûts
 
Nous ferions tourner automatiquement, à chaque modification, des tests unitaires sur le parseur (un cas par format de texte, PDF natif et OCR) et sur les contrôles qualité, ainsi que le script d'évaluation de l'étape 5 sur la vérité terrain. Cela nous alerterait si un changement de modèle ou de réglage dégrade la précision. Côté coûts, l'OCR est le poste principal, d'où l'intérêt de ne jamais ré-OCRiser un fichier déjà vu et de ne passer que les vrais scans par le modèle ; les PDF natifs sont lus directement.
 
### 9.6 Ce qui est en place et ce qui reste à faire
 
L'idempotence, la reprise sur erreur, la traçabilité du bronze et la mesure de la qualité sont **implémentées et testées**. La conteneurisation, l'orchestration, la gestion centralisée des secrets, la parallélisation et la supervision sont des **propositions** que nous n'avons pas eu le temps de mettre en œuvre.
 
---
 
## 10. Difficultés rencontrées, limites actuelles et pistes d'amélioration
 
### Difficultés rencontrées
 
- **Le manque de temps.** Nous avons préféré terminer correctement les étapes 1 à 5 plutôt que de survoler les neuf. Les étapes 6, 7 et 8 ne sont donc pas réalisées.
- **La nouveauté des technologies.** Nous découvrions en même temps l'architecture médaillon, le stockage en Parquet, l'OCR par modèle de vision et le protocole MCP. Beaucoup de temps est passé à comprendre le comportement du modèle d'OCR : il n'accepte aucune consigne texte, se comporte comme un simple moteur de transcription, et sa qualité dépend fortement de la résolution.
- **Des problèmes techniques d'ordinateur**, qui nous ont fait perdre du temps de développement et de test. [À préciser : panne, changement de poste, environnement à réinstaller.]
### Limites actuelles
 
- **Le système est incomplet.** Les données sont interrogeables en SQL (entrepôt DuckDB, section 8.1), mais il n'y a pas encore de serveur MCP ni d'agent : l'objectif final, poser une question en langage naturel, n'est pas atteint.
- **La vérité terrain est petite et peu indépendante.** Elle porte sur 20 factures (280 valeurs) et a été pré-remplie avec les valeurs extraites, puis vérifiée à la main. Ce procédé gagne du temps mais expose à un biais de confirmation. Avec 20 valeurs par champ, une seule erreur pèse 5 %.
- **Nos résultats sont probablement trop optimistes.** Nous obtenons 100 % de précision dès 72 DPI, mais nos scans sont propres. Des scans flous, penchés ou tachés donneraient sans doute de moins bons résultats, et notre échantillon ne permet pas de mesurer un taux d'erreur rare.
- **Le parseur est adapté à un format de facture précis.** Il fonctionne sur ces 100 factures, qui ont toutes la même structure. Un fournisseur avec une mise en page différente le mettrait en difficulté.
- **Les contrôles qualité restent peu éprouvés.** Un seul cas réel de facture signalée a été détecté (`V-2025-0001`). La quarantaine est restée vide, donc le chemin de rejet n'a pas été testé sur des cas réels. Le doublon fonctionnel créé au test 4 de l'étape 3 (même numéro A-2025-0003) n'a pas été confronté à la détection de doublons du silver.
- **Le stockage est local.** Le bronze et le silver sont des fichiers sur disque, sans sauvegarde. L'accès concurrent repose sur une règle (ouvrir l'entrepôt en lecture seule) : un utilisateur qui ouvrirait DuckDB en lecture-écriture bloquerait les autres programmes.
### Pistes d'amélioration
 
1. **Terminer les étapes 7 et 8**, dans cet ordre, car l'agent dépend du serveur MCP :
   - un serveur MCP en lecture seule, avec des descriptions d'outils soignées et des requêtes paramétrées contre l'injection SQL, qui renvoie les requêtes réellement exécutées ;
   - un agent dont le LLM se change par configuration, avec affichage des outils appelés et des requêtes SQL pour vérifier ses chiffres.
2. **Renforcer l'évaluation** : une vérité terrain plus large, saisie indépendamment de l'extraction, avec des scans volontairement dégradés (flou, rotation, bruit) pour mesurer la robustesse réelle de l'OCR.
3. **Rendre le parseur plus robuste** en le testant sur des mises en page variées, avec des tests unitaires pour chaque format.
4. **Appliquer la démarche d'industrialisation** de la section 9 : conteneurisation, planification, secrets centralisés et supervision.
