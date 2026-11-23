"""ÉTAPE 5 (a) — Préparer la vérité terrain.

Lancement :  uv run python etape5_verite_terrain.py

Tire 20 factures scannées au hasard (toujours les mêmes, grâce à une graine fixe)
et écrit un BROUILLON pré-rempli avec les valeurs du silver : verite_terrain.csv.

Ce brouillon doit ensuite être VÉRIFIÉ À LA MAIN, valeur par valeur, sur l'image
de chaque facture (et corrigé si besoin). Vérifier est bien plus rapide que tout saisir.
Le fichier vérifié est versionné dans Git : c'est notre référence.
"""

import random

import pandas as pd

import config

TAILLE_ECHANTILLON = 20
CHAMPS = ["numero_facture", "fournisseur", "siret_fournisseur", "client", "siret_client",
          "date_emission", "date_echeance", "categorie", "statut_paiement", "mode_paiement",
          "total_ht", "total_tva", "total_ttc", "nb_lignes"]
FICHIER = config.DOSSIER_PROJET / "verite_terrain.csv"

if __name__ == "__main__":
    if FICHIER.exists():
        print(f"{FICHIER.name} existe déjà : on ne l'écrase pas (il a peut-être été vérifié).")
        raise SystemExit(1)

    factures = pd.read_parquet(config.DOSSIER_SILVER / "factures.parquet")
    scans = sorted(factures.loc[factures.methode_extraction == "ocr", "source_fichier"])

    random.seed(42)  # graine fixe : le tirage est reproductible
    echantillon = sorted(random.sample(scans, TAILLE_ECHANTILLON))

    brouillon = factures[factures.source_fichier.isin(echantillon)]
    brouillon = brouillon[["source_fichier"] + CHAMPS].sort_values("source_fichier")
    brouillon.to_csv(FICHIER, index=False)
    print(f"Brouillon écrit : {FICHIER.name} ({len(brouillon)} factures) -> à vérifier sur les images !")
