"""Tests du serveur MCP (étape 7).

Lancement :  uv run python test_etape7_mcp.py

Le serveur est lancé comme le ferait un vrai client MCP (processus séparé, dialogue par stdio).
Chaque outil est appelé et son résultat est comparé à une requête SQL faite directement sur
l'entrepôt. On tente ensuite de modifier ou de lire des données interdites : tout doit être refusé.
"""

import asyncio
import json
import sys

from mcp import Client, StdioServerParameters

import config
from etape6_entrepot import ouvrir_entrepot

resultats = []


def verifier(nom, condition, detail=""):
    resultats.append(condition)
    print(f"  {'OK ' if condition else 'ÉCHEC'}  {nom}" + (f"  ({detail})" if detail and not condition else ""))


def sql_direct(sql):
    """Référence : la même question posée directement à l'entrepôt, sans passer par MCP."""
    con = ouvrir_entrepot()
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


async def appeler(client, outil, arguments=None):
    reponse = await client.call_tool(outil, arguments or {})
    return json.loads(reponse.content[0].text)


async def main():
    serveur = StdioServerParameters(command=sys.executable, args=["etape7_mcp.py"],
                                    cwd=str(config.DOSSIER_PROJET))
    async with Client(serveur) as client:

        print("\n1. Outils exposés")
        noms = sorted(t.name for t in (await client.list_tools()).tools)
        verifier("5 outils", noms == sorted(["lister_factures", "totaux_factures", "detail_facture",
                                             "schema_donnees", "requete_sql"]), noms)

        print("\n2. lister_factures")
        r = await appeler(client, "lister_factures", {"fournisseur": "Aubry"})
        attendu = sql_direct("SELECT count(*) FROM silver.factures WHERE fournisseur = 'Aubry'")[0][0]
        verifier(f"filtre fournisseur : {attendu} factures Aubry", r["nb_factures"] == attendu, r["nb_factures"])
        verifier("toutes les factures sont d'Aubry", all(f["fournisseur"] == "Aubry" for f in r["factures"]))
        verifier("la requête SQL est renvoyée", "FROM silver.factures" in r["sql"][0])
        r = await appeler(client, "lister_factures", {"limite": 3})
        verifier("limite respectée", r["nb_factures"] == 3)

        print("\n3. totaux_factures")
        r = await appeler(client, "totaux_factures",
                          {"statut_paiement": "En retard", "date_debut": "2025-01-01", "date_fin": "2025-12-31"})
        nb, ttc = sql_direct("SELECT count(*), sum(total_ttc) FROM silver.factures "
                             "WHERE statut_paiement = 'En retard' AND year(date_emission) = 2025")[0]
        verifier(f"en retard en 2025 : {nb} factures, {ttc} € TTC",
                 r["totaux"][0]["nb_factures"] == nb and r["totaux"][0]["total_ttc"] == str(ttc), r["totaux"])
        r2 = await appeler(client, "totaux_factures",
                           {"statut_paiement": "en retard", "date_debut": "2025-01-01", "date_fin": "2025-12-31"})
        verifier("statut écrit en minuscules : même résultat", r2["totaux"] == r["totaux"], r2["totaux"])
        r = await appeler(client, "totaux_factures", {"regrouper_par": "fournisseur"})
        total_groupes = sum(float(g["total_ttc"]) for g in r["totaux"])
        total_global = float(sql_direct("SELECT sum(total_ttc) FROM silver.factures")[0][0])
        verifier("somme des groupes = total global", abs(total_groupes - total_global) < 0.01)
        r = await appeler(client, "totaux_factures", {"regrouper_par": "couleur"})
        verifier("regroupement inconnu -> erreur explicite", "erreur" in r and "conseil" in r)
        r = await appeler(client, "totaux_factures", {"date_debut": "31/12/2025"})
        verifier("date invalide -> erreur explicite", "erreur" in r and "AAAA-MM-JJ" in r["conseil"])

        print("\n4. detail_facture")
        r = await appeler(client, "detail_facture", {"numero_facture": "P-2025-0002"})
        verifier("P-2025-0002 : TTC 19077.58 et 4 lignes",
                 r["facture"]["total_ttc"] == "19077.58" and len(r["lignes"]) == 4, r.get("facture"))
        verifier("2 requêtes SQL renvoyées", len(r["sql"]) == 2)
        r = await appeler(client, "detail_facture", {"numero_facture": "X-9999"})
        verifier("numéro inconnu -> erreur explicite", "erreur" in r)

        print("\n5. schema_donnees")
        r = await appeler(client, "schema_donnees")
        verifier("4 tables décrites", len(r["tables"]) == 4, list(r["tables"]))
        verifier("total_ttc de type DECIMAL",
                 r["tables"]["silver.factures"]["colonnes"]["total_ttc"].startswith("DECIMAL"))
        verifier("valeurs possibles des statuts",
                 r["valeurs_possibles"]["statut_paiement"] == ["En attente", "En retard", "Payée"])

        print("\n6. requete_sql")
        r = await appeler(client, "requete_sql",
                          {"sql": "SELECT fournisseur, count(*) AS n FROM silver.factures GROUP BY 1 ORDER BY 1"})
        verifier("SELECT accepté", "lignes" in r and len(r["lignes"]) == 8, r)
        r = await appeler(client, "requete_sql", {"sql": "SELECT colonne_inexistante FROM silver.factures"})
        verifier("erreur SQL -> message explicite + conseil", "erreur" in r and "conseil" in r)

        print("\n7. Tentatives de modification ou de lecture interdite (toutes doivent échouer)")
        attaques = {
            "DELETE": "DELETE FROM silver.factures",
            "DROP": "DROP VIEW silver.factures",
            "INSERT": "INSERT INTO silver.factures VALUES (1)",
            "CREATE": "CREATE TABLE pirate AS SELECT 1",
            "deux requêtes": "SELECT 1; DROP VIEW silver.factures",
            "lecture du .env": "SELECT * FROM read_text('.env')",
            "écriture de fichier": "COPY (SELECT * FROM silver.factures) TO '/tmp/vol.csv'",
            "lever la protection": "SET enable_external_access = true",
            "attacher une base": "ATTACH 'pirate.duckdb' AS p",
        }
        for nom, sql in attaques.items():
            r = await appeler(client, "requete_sql", {"sql": sql})
            verifier(f"{nom:20} refusé", "erreur" in r, r)
        # Injection SQL par un filtre : la valeur est un paramètre, elle ne peut pas changer la requête
        r = await appeler(client, "lister_factures", {"fournisseur": "x' OR 1=1 --"})
        verifier("injection SQL dans un filtre sans effet (0 facture)", r["nb_factures"] == 0, r["nb_factures"])

        print("\n8. Les données sont intactes")
        verifier("toujours 100 factures", sql_direct("SELECT count(*) FROM silver.factures")[0][0] == 100)

    print(f"\n{sum(resultats)}/{len(resultats)} tests réussis")
    sys.exit(0 if all(resultats) else 1)


if __name__ == "__main__":
    asyncio.run(main())
