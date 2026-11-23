# De la facture scannée à l'agent IA : rapport de projet

**Auteurs :** [noms du groupe] · **Module :** Architecture, data et IA · **Date :** novembre 2026

## 1. Objectif et état d'avancement

Nous avons construit une chaîne reproductible qui récupère 100 factures PDF (natives ou scannées), en extrait les informations, les stocke dans une architecture médaillon et permet de les interroger en langage naturel. Chaque étape se lance avec une seule commande (voir le `README.md`).

| Étape | Contenu | État |
|---|---|---|
| 1 à 5 | Récupération, OCR, bronze, silver, évaluation de l'OCR | Réalisées et testées |
| 6 | Entrepôt SQL (DuckDB) | Réalisée et testée |
| 7 | Serveur MCP | Réalisée, 29 tests automatiques |
| 8 | Agent IA | Réalisée avec **un seul LLM** (Gemma 4 12B) : par manque de temps, la comparaison avec un second LLM n'a pas été faite |
| 9 | Industrialisation | Proposition rédigée (section 4) |

## 2. Architecture et choix techniques

```
                 ┌──────────── STOCKAGE (fichiers Parquet, un seul exemplaire) ─────────────┐
 Bucket S3       │                                                                          │
 (Hyperfluid)    │   data/landing/        data/bronze/            data/silver/              │
   │  fetch      │   PDF bruts    ──►     run_<date>.parquet ──►  factures.parquet          │
   └──────────►  │                 │      (texte brut +           lignes_facture.parquet    │
                 │  texte ? ──pypdf┤       traçabilité,           quarantaine.parquet       │
                 │  image ? ──OCR──┘       jamais modifié)        (typé, contrôlé)          │
                 │          (LightOnOCR-3)                                                  │
                 └────────────────────────────────────────┬─────────────────────────────────┘
                                                          │ lecture seule
                 ┌────────────────── CALCUL ──────────────▼─────────────────────┐
                 │  DuckDB : entrepot.duckdb = 4 vues SQL, aucune donnée         │◄── DBeaver
                 └───────────────────────────┬──────────────────────────────────┘
                                             │
                  Serveur MCP (5 outils, lecture seule, SQL affiché) ◄── Claude Code
                                             │
                  Agent (LLM choisi dans .env : Gemma sur Hyperfluid, Ollama…)
```

| Brique | Choix | Justification |
|---|---|---|
| Langage | Python, gestionnaire `uv` (`uv.lock`) | Bibliothèques riches pour les PDF et les données ; dépendances figées, donc même exécution partout. |
| Détection texte / image | `pypdf`, page par page : moins de 20 caractères = image | Rapide, sans appel réseau ; un seul scan dans le PDF suffit à l'envoyer à l'OCR. |
| OCR | LightOnOCR-3 (imposé), API « OpenAI chat completions », 130 DPI | Le fournisseur est isolé dans une seule fonction, `appeler_ocr()`. 130 DPI est justifié en section 3. |
| Identification d'un fichier | Empreinte `sha256` du contenu | Indépendante du nom de fichier. |
| Stockage bronze / silver | Parquet ; bronze : un fichier par exécution | Format colonne typé et compact, lu directement par DuckDB ; le bronze n'est jamais réécrit. |
| Montants | `decimal(12,2)` | Un flottant ne représente pas exactement les centimes et fausserait les contrôles HT + TVA = TTC. |
| Entrepôt | DuckDB, fichier ne contenant que des vues | Moteur SQL embarqué (aucun serveur) qui lit le Parquet sans le copier : stockage et calcul séparés. |
| Accès des IA | Serveur MCP (SDK Python officiel) | Imposé ; un seul point d'accès, en lecture seule. |
| LLM de l'agent | API compatible OpenAI, profil choisi dans `.env` | Ce format est parlé par Hyperfluid (vLLM), Ollama, OpenAI ou Anthropic : changer de LLM ne touche pas au code. |
| Secrets | `.env` ignoré par Git, `.env.example` sans valeurs | Aucune clé dans le dépôt (vérifié dans tout l'historique Git). |

### Réalisation, étape par étape

**Étape 1 : récupération.** `etape1_recuperer.py` télécharge les factures absentes de `data/landing/` (relancé, il ne retélécharge rien) et classe chaque PDF : **50 « texte » et 50 « image »**, ce qui correspond aux suffixes `_texte` / `_scan` des noms de fichiers.

**Étape 2 : OCR.** La requête contient uniquement l'image (PNG en base64), avec `temperature 0.2`, `top_p 0.9`, `max_tokens 4096`, comme le prescrit la fiche du modèle. La sortie est du Markdown, avec les **tableaux en HTML**. Ce modèle n'est pas conversationnel : une consigne comme « donne le total en JSON » est ignorée, et elle **change le format de sortie** (coordonnées de blocs, lignes fusionnées). La fiche recommande des images dont le plus grand côté mesure 1540 px, soit 130 DPI pour une page A4 (mesures en section 3). Pour changer d'OCR, on modifie `OCR_BASE_URL` / `OCR_MODEL` dans `.env` (modèle compatible), ou on réécrit `appeler_ocr()` (autre moteur).

**Étape 3 : bronze.** Pour chaque PDF, `etape3_bronze.py` enregistre le texte brut et sa traçabilité : sha256, nom, taille, type, méthode (pypdf / OCR), modèle, DPI, date, durée, statut et erreur. Nos tests :
- une deuxième exécution affiche « 0 PDF à traiter, aucun appel OCR » ;
- une copie renommée n'est pas retraitée (même empreinte) ;
- avec une adresse d'OCR invalide, le pipeline ne plante pas : le document est enregistré en `erreur`, puis retraité au lancement suivant ;
- une réponse OCR vide est elle aussi traitée comme une erreur.

Le bronze n'est jamais modifié : c'est la seule trace de ce que l'OCR a lu, et il permet de reconstruire le silver sans refaire l'OCR.

**Étape 4 : silver.** Le texte pypdf (une cellule par ligne) et le texte OCR (Markdown + HTML) n'ont pas la même forme. Le parseur commence donc par les **normaliser** : il retire balises, gras et espaces insécables pour obtenir « une information par ligne ». Il extrait ensuite chaque champ avec la même règle quelle que soit la source (« Libellé : valeur », montant sur la même ligne ou la suivante).

Les contrôles qualité distinguent deux cas :
- une facture **rejetée** est inexploitable (champ obligatoire manquant ou illisible, date invalide, doublon fournisseur + numéro) : elle part en **quarantaine** avec un motif ;
- une facture **signalée** reste dans le silver, avec ses anomalies (HT + TVA ≠ TTC, somme des lignes ≠ HT, quantité × prix ≠ total de ligne, SIRET invalide).

Une valeur suspecte n'est jamais corrigée automatiquement : on ne saurait pas quelle valeur est fausse, et on masquerait l'erreur.

Résultat : **100 factures** (99 valides, 1 signalée), **271 lignes**, aucun doublon ni champ vide. La facture signalée, `V-2025-0001`, affiche réellement un TTC de 99 999,99 € pour 148,26 € HT. Le rejet (doublon, total illisible, date du 31/02) a été vérifié par simulation.

**Étape 6 : entrepôt.** `data/entrepot.duckdb` ne contient que 4 vues (`bronze.documents`, `silver.factures`, `silver.lignes_facture`, `silver.quarantaine`) qui lisent les Parquet au moment de la requête. Exemple en SQL : factures en retard en 2025, **12 factures, 106 886,43 €**.
- **Accès concurrent.** DuckDB accepte plusieurs lecteurs mais un seul écrivain, qui bloque alors les autres (vérifié). Tous les accès, y compris DBeaver, se font donc en lecture seule. Le silver peut être régénéré pendant qu'on consulte l'entrepôt.
- **Portabilité.** Le fichier `.duckdb` n'est pas versionné : une commande le recrée avec les chemins de la machine (poste, collègue ou conteneur).

[À compléter : capture de DBeaver connecté en lecture seule.]

**Étape 7 : serveur MCP.** `etape7_mcp.py` expose 5 outils en lecture seule : `lister_factures`, `totaux_factures` (avec filtres et regroupements), `detail_facture`, `schema_donnees` et `requete_sql`. Chaque réponse contient **les requêtes SQL réellement exécutées**. Les descriptions disent quand utiliser chaque outil et donnent les valeurs possibles des filtres. En cas d'erreur, l'outil renvoie un message et un conseil (`"Utiliser le format AAAA-MM-JJ"`) pour que le LLM se corrige.

La sécurité repose sur quatre protections empilées :
1. les filtres passent en **paramètres** (`?`), donc pas d'injection SQL ;
2. `requete_sql` n'accepte qu'**un seul `SELECT`** ;
3. l'entrepôt est ouvert **en lecture seule** ;
4. DuckDB ne peut lire **que** `data/bronze` et `data/silver`, et cette configuration est verrouillée.

La 4e protection est indispensable : `SELECT * FROM read_text('.env')` est un `SELECT` valide, qui aurait livré nos clés d'API. Le script `test_etape7_mcp.py` passe **29 tests sur 29**, dont 10 tentatives d'attaque (`DELETE`, `DROP`, `COPY`, lecture du `.env`, injection `x' OR 1=1 --`…), toutes refusées.

[À compléter : capture d'une conversation dans Claude Code utilisant le serveur, déclaré dans `.mcp.json`.]

**Étape 8 : agent.** `etape8_agent.py` lance le serveur MCP, transmet ses outils au LLM et exécute les appels demandés. À chaque étape, il affiche l'outil, ses arguments, le SQL et un aperçu du résultat. Il garde l'historique de la conversation, limite chaque question à 8 tours d'outils, et s'arrête proprement (`quitter`, Ctrl+D).

**Le LLM se choisit par configuration** : un profil `P` est décrit par `P_BASE_URL`, `P_API_KEY` et `P_MODEL` dans `.env`, et sélectionné avec `--llm P`. Pour empêcher l'agent d'inventer des chiffres, la consigne système interdit tout nombre qui ne vient pas d'un outil et impose de faire calculer les sommes par la base (`totaux_factures`).

Résultats avec Gemma 4 12B (Hyperfluid), tous vérifiés en SQL direct :

| Question | Outil choisi | Réponse | SQL direct |
|---|---|---|---|
| Montant TTC des factures en retard en 2025 ? | `totaux_factures` (statut + période) | 106 886,43 € | identique |
| Quel fournisseur a le plus gros total TTC ? | `totaux_factures` (regroupé par fournisseur) | Aubry, 295 611,58 € | identique |
| Et combien de factures a-t-il émises ? | aucun (historique de la conversation) | 11 | identique |
| Y a-t-il des factures suspectes ? | `lister_factures` (statut qualité) | V-2025-0001, avec explication | identique |

Observations : 1 à 5 s par réponse, et un choix d'outils pertinent. Gemma a d'abord écrit le statut en minuscules (« en retard ») : avec un filtre exact, la réponse aurait été « 0 facture », fausse mais crédible. Nous avons rendu les filtres insensibles à la casse.

**Par manque de temps, l'agent n'a été testé qu'avec un seul LLM.** Le profil d'un modèle local (Ollama, `qwen2.5:7b`) est prêt dans `.env.example`, mais il n'a pas été exécuté. Le critère « une même question posée avec deux LLM » n'est donc pas démontré, et nous ne pouvons pas comparer un petit modèle local à un grand modèle hébergé.

## 3. Évaluation de l'OCR (étape 5)

**Méthode.** Nous avons pris 20 factures scannées tirées au hasard (graine fixe) et vérifié à la main, sur l'image, 14 champs par facture, soit **280 valeurs** (`verite_terrain.csv`). Pour aller vite, les valeurs ont été pré-remplies avec l'extraction puis vérifiées une à une ; aucune n'a dû être corrigée. Chaque facture passe dans la chaîne OCR + parseur silver à quatre résolutions. Une valeur est juste seulement si elle est exactement égale à la vérité terrain. Commande : `uv run python etape5_evaluation.py`.

| Champ | 50 DPI | 72 DPI | 130 DPI | 200 DPI |
|---|---|---|---|---|
| client | 50 % | 100 % | 100 % | 100 % |
| siret_fournisseur | 55 % | 100 % | 100 % | 100 % |
| numero_facture | 75 % | 100 % | 100 % | 100 % |
| siret_client, date_echeance, categorie | 85 % | 100 % | 100 % | 100 % |
| mode_paiement, nb_lignes | 90 % | 100 % | 100 % | 100 % |
| date_emission, total_ht, total_ttc | 95 % | 100 % | 100 % | 100 % |
| fournisseur, statut_paiement, total_tva | 100 % | 100 % | 100 % | 100 % |
| **Ensemble des 280 valeurs** | **85,7 %** | **100 %** | **100 %** | **100 %** |
| Temps OCR moyen par page | ≈ 6 s * | ≈ 6 s * | 8,3 s | 10,0 s |

\* mesuré sur une seule page ; les temps varient avec la charge du service (jusqu'à 3,5 s par page à 130 DPI dans une autre série de mesures).

**Analyse.**
- **Un seuil net.** À partir de 72 DPI, tout est exact ; en dessous, la qualité s'effondre. Monter au-delà de 130 DPI n'apporte rien et coûte du temps (+20 % à 200 DPI, +57 % à 300 DPI sur une page de test).
- **Les champs les plus fragiles** sont les **noms propres** et les **longues suites de chiffres**, que le contexte ne permet pas de deviner : « Fleury » est lu « Finruy », un chiffre change dans un SIRET, « P-2025-0002 » devient « P-2625-0002 ». Les champs à peu de valeurs possibles (statut, taux de TVA) résistent.
- **L'OCR se trompe sans prévenir** : 31 des 40 erreurs à 50 DPI sont des valeurs **fausses mais plausibles**, et non des champs vides. Nos contrôles qualité repèrent 13 des 18 factures erronées ; les 5 autres passeraient pour valides (par exemple un nom de client faux avec des montants justes).
- **Choix : 130 DPI.** C'est la recommandation du modèle, avec 100 % de valeurs exactes et une marge pour des scans réels de moins bonne qualité.
- **Taille d'échantillon.** Avec 20 valeurs par champ, une erreur pèse 5 %. Cela suffit pour voir un écart net, pas pour mesurer un taux d'erreur rare : « 100 % » ne signifie pas « zéro erreur ».

## 4. Industrialisation (étape 9)

Notre chaîne tourne sur un poste, lancée à la main. Pour des milliers de factures par mois et plusieurs utilisateurs, nous traitons en priorité les sujets les plus risqués.

**1. Automatiser sans risque.** Le pipeline est déjà *idempotent*. Le sha256 évite tout retraitement, et les erreurs sont retentées au passage suivant : un lancement interrompu ou doublé ne crée ni doublon ni perte. Nous lancerions `etape1 → etape3 → etape4` à intervalle régulier, avec un simple cron dans une image Docker aux dépendances figées (`uv.lock`). Un orchestrateur (Airflow, Dagster) ne se justifierait qu'avec plusieurs chaînes à coordonner.

**2. Sécuriser les secrets et les accès.** Les clés passeraient du `.env` à un gestionnaire de secrets (Vault ou celui du cloud), injecté au démarrage. Nous prévoirions une clé par service et par environnement, avec le minimum de droits (lecture seule sur le bucket) et une rotation régulière. Le serveur MCP est déjà en lecture seule, avec un accès aux fichiers limité. Il resterait à authentifier les utilisateurs de l'agent et à journaliser qui pose quelle question.

**3. Faire monter l'OCR en charge.** C'est le seul goulot d'étranglement : 3,5 à 8,3 s par page, soit 30 minutes à 1 heure pour 1 000 factures (environ 500 pages scannées) en séquentiel. Nous traiterions les pages en parallèle avec une file de tâches et plusieurs workers, en limitant le débit pour ne pas saturer le service et en espaçant les relances. Nous resterions à 130 DPI (section 3). Isoler le fournisseur dans `appeler_ocr()` permet de changer de modèle si le coût l'exige.

**4. Superviser.** Nous suivrions quelques indicateurs déjà disponibles dans nos tables : factures ingérées par jour, taux d'erreur OCR, factures signalées ou en quarantaine, durée par page. Une alerte se déclencherait si le taux d'erreur monte ou si rien n'arrive pendant un jour ouvré. Les factures signalées iraient dans une file de revue humaine.

**5. Tester et maîtriser les coûts.** Nous lancerions automatiquement, à chaque modification, les tests du serveur MCP (déjà écrits), des tests du parseur pour chaque format de texte, et l'évaluation sur la vérité terrain, pour détecter une baisse de précision après un changement de modèle. L'OCR est le poste de coût principal : seuls les vrais scans y passent, une seule fois.

**Déjà en place :** idempotence, reprise sur erreur, traçabilité, mesure de la qualité, accès IA en lecture seule. **À faire :** conteneur, planification, secrets centralisés, parallélisation, supervision.

## 5. Difficultés, limites et pistes d'amélioration

**Difficultés rencontrées**
- **Le manque de temps.** Nous avons préféré valider chaque étape avant de passer à la suivante. Conséquence : l'agent n'a été testé qu'avec un seul LLM.
- **La nouveauté des technologies.** Nous découvrions en même temps l'architecture médaillon, le Parquet, l'OCR par modèle de vision et MCP. Comprendre le modèle d'OCR (pas de consigne texte, forte dépendance à la résolution, format de sortie variable) a pris beaucoup de temps.
- **Des problèmes techniques d'ordinateur**, qui nous ont fait perdre du temps de développement et de test. [À préciser.]

**Limites actuelles**
- **Un seul LLM testé** pour l'agent : l'interchangeabilité est prévue par la configuration, mais elle n'est pas démontrée.
- **Une vérité terrain petite** (280 valeurs) et pré-remplie par l'extraction, ce qui l'expose à un biais de confirmation. Les scans du jeu sont propres, donc nos 100 % sont probablement optimistes.
- **Un parseur adapté à une seule mise en page** de facture ; un autre fournisseur le mettrait en difficulté.
- **Des contrôles qualité peu éprouvés** : une seule facture signalée en conditions réelles, et le rejet n'a été testé que par simulation.
- **Un stockage local**, sans sauvegarde ; l'accès concurrent repose sur la règle « lecture seule pour tous ».

**Pistes d'amélioration**
1. Tester l'agent avec un second LLM (profil Ollama déjà prêt) et comparer vitesse, choix des outils et exactitude.
2. Élargir l'évaluation : vérité terrain saisie indépendamment, scans volontairement dégradés (flou, rotation, bruit).
3. Ajouter des tests unitaires du parseur sur des mises en page variées, lancés en intégration continue.
4. Mettre en œuvre l'industrialisation de la section 4.
