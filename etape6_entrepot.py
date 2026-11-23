"""ÉTAPE 6 — L'entrepôt de données : rendre le bronze et le silver interrogeables en SQL.

Lancement :  uv run python etape6_entrepot.py

Crée (ou recrée) le fichier data/entrepot.duckdb. Il ne contient AUCUNE donnée,
uniquement des VUES qui lisent les fichiers Parquet :

    bronze.documents         -> data/bronze/run_*.parquet
    silver.factures          -> data/silver/factures.parquet
    silver.lignes_facture    -> data/silver/lignes_facture.parquet
    silver.quarantaine       -> data/silver/quarantaine.parquet

Séparation stockage / calcul : les données n'existent qu'une fois (les fichiers Parquet) ;
DuckDB ne fait que les lire au moment de la requête. Une vue est donc toujours à jour :
pas besoin de relancer ce script quand le bronze ou le silver changent.

Chemins : les vues contiennent le chemin complet des fichiers Parquet SUR CETTE MACHINE.
Le fichier .duckdb n'est donc pas versionné : chacun le régénère avec cette commande
(sur son poste, chez un collègue, dans un conteneur).
"""

import duckdb

import config

VUES = {
    "bronze.documents": config.DOSSIER_BRONZE / "run_*.parquet",
    "silver.factures": config.DOSSIER_SILVER / "factures.parquet",
    "silver.lignes_facture": config.DOSSIER_SILVER / "lignes_facture.parquet",
    "silver.quarantaine": config.DOSSIER_SILVER / "quarantaine.parquet",
}


def ouvrir_entrepot():
    """Connexion en LECTURE SEULE à l'entrepôt, pour les programmes (serveur MCP, agent...).

    Plusieurs programmes peuvent ouvrir l'entrepôt en lecture seule en même temps ;
    en lecture-écriture, DuckDB n'autorise qu'un seul programme à la fois.
    """
    return duckdb.connect(str(config.FICHIER_ENTREPOT), read_only=True)


def creer_entrepot():
    config.FICHIER_ENTREPOT.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(config.FICHIER_ENTREPOT))  # seule connexion en écriture : le temps de créer les vues
    con.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    con.execute("CREATE SCHEMA IF NOT EXISTS silver")
    for vue, chemin in VUES.items():
        # union_by_name : les fichiers bronze de différentes exécutions sont assemblés par nom de colonne
        con.execute(f"CREATE OR REPLACE VIEW {vue} AS "
                    f"SELECT * FROM read_parquet('{chemin.as_posix()}', union_by_name = true)")
    con.close()
    print(f"Entrepôt créé : {config.FICHIER_ENTREPOT.relative_to(config.DOSSIER_PROJET)}")


if __name__ == "__main__":
    creer_entrepot()

    # Vérification : une requête SQL sur chaque vue
    con = ouvrir_entrepot()
    for vue in VUES:
        nb = con.execute(f"SELECT count(*) FROM {vue}").fetchone()[0]
        print(f"  {vue:24} {nb:4} lignes")
    con.close()
