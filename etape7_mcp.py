"""ÉTAPE 7 — Serveur MCP : donner à une IA un accès SÉCURISÉ et EN LECTURE SEULE à l'entrepôt.

Lancement (normalement fait par le client MCP : Claude Code, Claude Desktop, notre agent...) :
    uv run python etape7_mcp.py

Outils exposés :
    lister_factures   liste des factures avec filtres
    totaux_factures   nombre et totaux HT / TVA / TTC avec les mêmes filtres (+ regroupement)
    detail_facture    une facture et ses lignes
    schema_donnees    tables, colonnes et valeurs possibles
    requete_sql       requête SQL libre, en lecture seule

Chaque réponse contient la clé "sql" : les requêtes réellement exécutées (transparence).

Sécurité (les arguments viennent d'un LLM, donc d'une source NON FIABLE) :
  1. filtres passés en PARAMÈTRES (?) : une valeur n'est jamais collée dans le texte SQL ;
  2. requete_sql n'accepte qu'UNE requête de type SELECT ;
  3. entrepôt ouvert en LECTURE SEULE (toute écriture est refusée par DuckDB) ;
  4. DuckDB ne peut lire QUE data/bronze et data/silver (impossible de lire .env ou d'écrire
     un fichier), et cette configuration est verrouillée.
"""

import datetime
import decimal

import duckdb
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

import config

MAX_LIGNES = 200  # on ne renvoie jamais plus de 200 lignes au LLM (coût, lisibilité)
LECTURE_SEULE = ToolAnnotations(readOnlyHint=True)

serveur = MCPServer(
    name="factures",
    instructions=(
        "Accès en lecture seule aux factures fournisseurs (couche silver). "
        "Les montants sont en euros. Utilise totaux_factures pour tout calcul de somme ou de nombre, "
        "plutôt que d'additionner toi-même les lignes de lister_factures."
    ),
)


# ---------------------------------------------------------------------------
# Connexion et exécution
# ---------------------------------------------------------------------------

def connexion():
    """Ouvre l'entrepôt en lecture seule, avec un accès aux fichiers limité aux données."""
    con = duckdb.connect(str(config.FICHIER_ENTREPOT), read_only=True)
    dossiers = [str(config.DOSSIER_BRONZE) + "/", str(config.DOSSIER_SILVER) + "/"]
    con.execute(f"SET allowed_directories = {dossiers}")
    con.execute("SET enable_external_access = false")  # interdit tout autre fichier / URL
    con.execute("SET lock_configuration = true")       # empêche de revenir sur ces réglages
    return con


def en_json(valeur):
    """Convertit les types SQL en types JSON : montants et dates deviennent du texte exact."""
    if isinstance(valeur, decimal.Decimal):
        return str(valeur)  # "19077.58" : pas de float, donc pas d'arrondi
    if isinstance(valeur, (datetime.date, datetime.datetime)):
        return valeur.isoformat()
    return valeur


def executer(con, sql, parametres=()):
    """Exécute une requête et renvoie les lignes sous forme de dictionnaires (au plus MAX_LIGNES)."""
    curseur = con.execute(sql, list(parametres))
    colonnes = [c[0] for c in curseur.description]
    lignes = curseur.fetchmany(MAX_LIGNES + 1)
    return {
        "lignes": [{c: en_json(v) for c, v in zip(colonnes, l)} for l in lignes[:MAX_LIGNES]],
        "tronque": len(lignes) > MAX_LIGNES,
    }


def erreur(message, sql=None, conseil=None):
    """Réponse d'erreur explicite : le LLM peut lire le message et corriger son appel."""
    return {"erreur": message, "sql": sql, "conseil": conseil}


def construire_filtres(fournisseur, client, statut_paiement, statut_qualite, categorie,
                       date_debut, date_fin):
    """Construit la clause WHERE avec des paramètres « ? » (jamais de valeur collée dans le SQL)."""
    conditions, parametres = [], []
    if fournisseur:
        conditions.append("fournisseur ILIKE ?")       # recherche partielle, sans casse
        parametres.append(f"%{fournisseur}%")
    if client:
        conditions.append("client ILIKE ?")
        parametres.append(f"%{client}%")
    if statut_paiement:
        conditions.append("statut_paiement = ?")
        parametres.append(statut_paiement)
    if statut_qualite:
        conditions.append("statut_qualite = ?")
        parametres.append(statut_qualite)
    if categorie:
        conditions.append("categorie = ?")
        parametres.append(categorie)
    if date_debut:
        conditions.append("date_emission >= ?")
        parametres.append(datetime.date.fromisoformat(date_debut))
    if date_fin:
        conditions.append("date_emission <= ?")
        parametres.append(datetime.date.fromisoformat(date_fin))
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    return where, parametres


DESCRIPTION_FILTRES = """
    Filtres (tous facultatifs, combinables) :
      fournisseur      : nom ou partie du nom (ex. "Aubry", "Maury")
      client           : nom ou partie du nom (ex. "Mace")
      statut_paiement  : "Payée", "En retard" ou "En attente"
      statut_qualite   : "valide" ou "signalee" (facture suspecte, voir la colonne anomalies)
      categorie        : "Informatique", "Fournitures", "Maintenance" ou "Conseil"
      date_debut, date_fin : bornes sur la date d'émission, format AAAA-MM-JJ (incluses)
"""


# ---------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------

@serveur.tool(annotations=LECTURE_SEULE, description=f"""
    Liste les factures (une ligne par facture : numéro, fournisseur, client, dates, statut,
    totaux HT / TVA / TTC). Pour un NOMBRE ou une SOMME, utiliser plutôt totaux_factures.
    {DESCRIPTION_FILTRES}
      limite           : nombre maximum de factures renvoyées (défaut 50, maximum 200)
    Renvoie les factures triées par date d'émission et la requête SQL exécutée.""")
def lister_factures(fournisseur: str | None = None, client: str | None = None,
                    statut_paiement: str | None = None, statut_qualite: str | None = None,
                    categorie: str | None = None, date_debut: str | None = None,
                    date_fin: str | None = None, limite: int = 50) -> dict:
    try:
        where, parametres = construire_filtres(fournisseur, client, statut_paiement,
                                               statut_qualite, categorie, date_debut, date_fin)
    except ValueError:
        return erreur("Date invalide.", conseil="Utiliser le format AAAA-MM-JJ, par exemple 2025-01-31.")
    limite = max(1, min(int(limite), MAX_LIGNES))
    sql = ("SELECT numero_facture, fournisseur, client, date_emission, date_echeance, "
           "statut_paiement, categorie, total_ht, total_tva, total_ttc, statut_qualite "
           f"FROM silver.factures{where} ORDER BY date_emission, numero_facture LIMIT {limite}")
    with connexion() as con:
        resultat = executer(con, sql, parametres)
    return {"sql": [sql], "parametres": [str(p) for p in parametres],
            "nb_factures": len(resultat["lignes"]), "factures": resultat["lignes"]}


REGROUPEMENTS = {  # liste blanche : seules ces expressions peuvent être insérées dans le SQL
    "fournisseur": "fournisseur",
    "client": "client",
    "statut_paiement": "statut_paiement",
    "statut_qualite": "statut_qualite",
    "categorie": "categorie",
    "annee": "year(date_emission)",
    "mois": "strftime(date_emission, '%Y-%m')",
}


@serveur.tool(annotations=LECTURE_SEULE, description=f"""
    Calcule le NOMBRE de factures et la SOMME des montants HT, TVA et TTC (en euros),
    calculés exactement par la base. À utiliser pour toute question « combien », « total », « montant ».
    {DESCRIPTION_FILTRES}
      regrouper_par    : facultatif, un total par groupe : "fournisseur", "client", "statut_paiement",
                         "statut_qualite", "categorie", "annee" ou "mois"
    Renvoie les totaux et la requête SQL exécutée.""")
def totaux_factures(fournisseur: str | None = None, client: str | None = None,
                    statut_paiement: str | None = None, statut_qualite: str | None = None,
                    categorie: str | None = None, date_debut: str | None = None,
                    date_fin: str | None = None, regrouper_par: str | None = None) -> dict:
    try:
        where, parametres = construire_filtres(fournisseur, client, statut_paiement,
                                               statut_qualite, categorie, date_debut, date_fin)
    except ValueError:
        return erreur("Date invalide.", conseil="Utiliser le format AAAA-MM-JJ, par exemple 2025-01-31.")
    if regrouper_par and regrouper_par not in REGROUPEMENTS:
        return erreur(f"Regroupement inconnu : {regrouper_par!r}.",
                      conseil="Valeurs possibles : " + ", ".join(REGROUPEMENTS))

    mesures = ("count(*) AS nb_factures, coalesce(sum(total_ht), 0) AS total_ht, "
               "coalesce(sum(total_tva), 0) AS total_tva, coalesce(sum(total_ttc), 0) AS total_ttc")
    if regrouper_par:
        groupe = REGROUPEMENTS[regrouper_par]
        sql = (f"SELECT {groupe} AS {regrouper_par}, {mesures} FROM silver.factures{where} "
               f"GROUP BY 1 ORDER BY 1")
    else:
        sql = f"SELECT {mesures} FROM silver.factures{where}"
    with connexion() as con:
        resultat = executer(con, sql, parametres)
    return {"sql": [sql], "parametres": [str(p) for p in parametres], "totaux": resultat["lignes"]}


@serveur.tool(annotations=LECTURE_SEULE, description="""
    Donne le détail complet d'UNE facture (fournisseur, client, SIRET, dates, statuts, totaux,
    anomalies éventuelles, fichier source) et toutes ses lignes (désignation, quantité,
    prix unitaire HT, taux de TVA, total HT).
      numero_facture : numéro exact, par exemple "P-2025-0002"
    Renvoie la facture, ses lignes et les requêtes SQL exécutées.""")
def detail_facture(numero_facture: str) -> dict:
    sql_facture = "SELECT * FROM silver.factures WHERE numero_facture = ?"
    sql_lignes = "SELECT * FROM silver.lignes_facture WHERE numero_facture = ? ORDER BY num_ligne"
    with connexion() as con:
        facture = executer(con, sql_facture, [numero_facture])["lignes"]
        lignes = executer(con, sql_lignes, [numero_facture])["lignes"]
    if not facture:
        return erreur(f"Aucune facture numéro {numero_facture!r}.", sql=[sql_facture],
                      conseil="Vérifier le numéro (format « P-2025-0002 ») ou le chercher avec lister_factures.")
    return {"sql": [sql_facture, sql_lignes], "parametres": [numero_facture],
            "facture": facture[0], "lignes": lignes}


DESCRIPTIONS_TABLES = {
    "silver.factures": "une ligne par facture validée (montants en euros, DECIMAL exact)",
    "silver.lignes_facture": "une ligne par ligne de facture ; jointure sur numero_facture",
    "silver.quarantaine": "documents rejetés (inexploitables ou doublons) avec leur motif",
    "bronze.documents": "texte brut extrait de chaque PDF (OCR ou natif) et métadonnées de traçabilité",
}


@serveur.tool(annotations=LECTURE_SEULE, description="""
    Décrit les données disponibles : tables, colonnes, types, et valeurs possibles des colonnes
    de statut. À appeler AVANT d'écrire une requête avec requete_sql.""")
def schema_donnees() -> dict:
    sql_colonnes = ("SELECT table_schema || '.' || table_name AS table_, column_name, data_type "
                    "FROM information_schema.columns WHERE table_schema IN ('bronze', 'silver') "
                    "ORDER BY table_schema DESC, table_name, ordinal_position")
    sql_valeurs = ("SELECT 'statut_paiement' AS colonne, list(DISTINCT statut_paiement ORDER BY statut_paiement) AS valeurs FROM silver.factures "
                   "UNION ALL SELECT 'statut_qualite', list(DISTINCT statut_qualite ORDER BY statut_qualite) FROM silver.factures "
                   "UNION ALL SELECT 'categorie', list(DISTINCT categorie ORDER BY categorie) FROM silver.factures")
    with connexion() as con:
        colonnes = con.execute(sql_colonnes).fetchall()
        valeurs = con.execute(sql_valeurs).fetchall()
    tables = {}
    for table, colonne, type_ in colonnes:
        tables.setdefault(table, {"description": DESCRIPTIONS_TABLES.get(table, ""), "colonnes": {}})
        tables[table]["colonnes"][colonne] = type_
    return {"sql": [sql_colonnes, sql_valeurs], "tables": tables,
            "valeurs_possibles": {colonne: liste for colonne, liste in valeurs}}


@serveur.tool(annotations=LECTURE_SEULE, description=f"""
    Exécute UNE requête SQL (dialecte DuckDB) en LECTURE SEULE, pour les questions que les autres
    outils ne couvrent pas. Seules les requêtes SELECT (ou WITH ... SELECT) sont acceptées ;
    toute modification est refusée. Tables : silver.factures, silver.lignes_facture,
    silver.quarantaine, bronze.documents (appeler schema_donnees pour les colonnes).
    Au plus {MAX_LIGNES} lignes sont renvoyées.
      sql : la requête, par exemple
            "SELECT fournisseur, sum(total_ttc) FROM silver.factures GROUP BY fournisseur"
    Renvoie les lignes de résultat et la requête exécutée.""")
def requete_sql(sql: str) -> dict:
    with connexion() as con:
        # Vérification AVANT exécution : une seule instruction, et de type SELECT
        try:
            instructions = con.extract_statements(sql)
        except duckdb.Error as e:
            return erreur(f"Requête SQL invalide : {e}", sql=[sql],
                          conseil="Corriger la syntaxe ; appeler schema_donnees pour les noms de colonnes.")
        if len(instructions) != 1:
            return erreur(f"Une seule requête à la fois ({len(instructions)} reçues).", sql=[sql],
                          conseil="Envoyer une seule requête SELECT, sans « ; » entre plusieurs requêtes.")
        if instructions[0].type != duckdb.StatementType.SELECT:
            return erreur(f"Requête refusée : seules les lectures (SELECT) sont autorisées, "
                          f"reçu {instructions[0].type.name}.", sql=[sql],
                          conseil="Ce serveur est en lecture seule : reformuler en SELECT.")
        try:
            resultat = executer(con, sql)
        except duckdb.Error as e:
            return erreur(f"Erreur à l'exécution : {e}", sql=[sql],
                          conseil="Vérifier les noms de tables et de colonnes avec schema_donnees.")
    return {"sql": [sql], "nb_lignes": len(resultat["lignes"]), "tronque": resultat["tronque"],
            "lignes": resultat["lignes"]}


if __name__ == "__main__":
    serveur.run()  # transport « stdio » : le client lance ce script et dialogue par l'entrée/sortie standard
