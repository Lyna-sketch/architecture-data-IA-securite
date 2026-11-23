"""ÉTAPE 5 (b) — Mesurer la qualité de l'OCR, champ par champ, pour plusieurs réglages.

Lancement :  uv run python etape5_evaluation.py              (réglages par défaut : 50, 72, 130 et 200 DPI)
             uv run python etape5_evaluation.py 100 300      (autres résolutions)

Pour chaque résolution et chaque facture de verite_terrain.csv :
  1. OCR de la page à cette résolution (le texte est gardé dans data/evaluation/ocr_<dpi>/,
     donc relancer le script ne refait pas les appels OCR) ;
  2. extraction des champs avec LE MÊME parseur que la couche silver (etape4_silver.py) ;
  3. comparaison de chaque champ avec la vérité terrain.

Résultat : un tableau « précision par champ » (affiché et enregistré dans data/evaluation/).
"""

import sys
import time

import pandas as pd

import config
from etape2_ocr import appeler_ocr, page_en_image
from etape4_silver import parser_facture
from etape5_verite_terrain import CHAMPS, FICHIER as FICHIER_VERITE


def texte_ocr(fichier, dpi):
    """Texte OCR d'une facture à une résolution donnée (mis en cache sur disque)."""
    cache = config.DOSSIER_EVALUATION / f"ocr_{dpi}" / (fichier + ".md")
    if cache.exists() and cache.stat().st_size > 0:  # un fichier vide n'est pas un résultat
        return cache.read_text(), None
    cache.parent.mkdir(parents=True, exist_ok=True)
    debut = time.time()
    texte = appeler_ocr(page_en_image(config.DOSSIER_LANDING / fichier, dpi=dpi))
    duree = time.time() - debut
    # Écriture dans un fichier temporaire puis renommage : si le script est coupé
    # pendant l'écriture, on ne laisse pas un fichier à moitié écrit dans le cache.
    temporaire = cache.with_suffix(".tmp")
    temporaire.write_text(texte)
    temporaire.replace(cache)
    return texte, duree


def en_texte(valeur):
    """Met une valeur extraite au même format que le CSV (dates AAAA-MM-JJ, montants 1234.50)."""
    return "" if valeur is None else str(valeur)


def evaluer(dpi, verite):
    """Compare l'extraction à la vérité terrain pour une résolution. Renvoie (résultats, erreurs, durées)."""
    resultats, erreurs, durees = [], [], []
    for attendu in verite.itertuples(index=False):
        texte, duree = texte_ocr(attendu.source_fichier, dpi)
        if duree is not None:
            durees.append(duree)
        facture, lignes = parser_facture(texte)
        facture["nb_lignes"] = len(lignes)

        for champ in CHAMPS:
            vrai, lu = getattr(attendu, champ), en_texte(facture[champ])
            resultats.append({"dpi": dpi, "champ": champ, "correct": vrai == lu})
            if vrai != lu:
                erreurs.append({"dpi": dpi, "fichier": attendu.source_fichier,
                                "champ": champ, "attendu": vrai, "lu": lu})
    return resultats, erreurs, durees


if __name__ == "__main__":
    reglages = [int(x) for x in sys.argv[1:]] or [50, 72, 130, 200]
    verite = pd.read_csv(FICHIER_VERITE, dtype=str, keep_default_na=False)
    print(f"Vérité terrain : {len(verite)} factures x {len(CHAMPS)} champs = {len(verite) * len(CHAMPS)} valeurs\n")

    tous_resultats, toutes_erreurs, temps = [], [], {}
    for dpi in reglages:
        print(f"Évaluation à {dpi} DPI...")
        resultats, erreurs, durees = evaluer(dpi, verite)
        tous_resultats += resultats
        toutes_erreurs += erreurs
        temps[dpi] = sum(durees) / len(durees) if durees else None

    # Tableau : précision (en %) par champ et par résolution
    df = pd.DataFrame(tous_resultats)
    tableau = df.pivot_table(index="champ", columns="dpi", values="correct", aggfunc="mean") * 100
    tableau = tableau.reindex(CHAMPS)
    tableau.loc["TOUS LES CHAMPS"] = df.groupby("dpi")["correct"].mean() * 100
    tableau.columns = [f"{dpi} DPI" for dpi in tableau.columns]

    print("\nPrécision par champ (% de valeurs exactes) :")
    print(tableau.round(1).to_string())
    print("\nTemps OCR moyen par page : " + ", ".join(
        f"{dpi} DPI = {t:.1f} s" if t else f"{dpi} DPI = (déjà en cache)" for dpi, t in temps.items()))

    if toutes_erreurs:
        print("\nDétail des erreurs :")
        print(pd.DataFrame(toutes_erreurs).to_string(index=False))

    config.DOSSIER_EVALUATION.mkdir(parents=True, exist_ok=True)
    tableau.round(1).to_csv(config.DOSSIER_EVALUATION / "precision_par_champ.csv")
    pd.DataFrame(toutes_erreurs).to_csv(config.DOSSIER_EVALUATION / "erreurs.csv", index=False)
    print("\nRésultats enregistrés dans data/evaluation/")
