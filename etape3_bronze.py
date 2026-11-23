"""ÉTAPE 3 — Couche bronze : le texte brut de chaque facture, avec sa traçabilité.

Lancement :  uv run python etape3_bronze.py        (traite tous les nouveaux PDF)
             uv run python etape3_bronze.py 5      (au plus 5 nouveaux PDF, pour tester)

Pour chaque PDF de data/landing/ :
  - PDF « texte » -> on lit sa couche texte avec pypdf (pas d'OCR) ;
  - PDF « image » -> on envoie chaque page au modèle d'OCR.

Règles de la couche bronze :
  1. Un fichier « déjà vu » est reconnu par l'empreinte sha256 de son CONTENU (pas par son nom).
  2. Incrémental : un fichier déjà ingéré avec succès n'est jamais retraité (ni ré-OCRisé).
  3. On ne modifie et ne supprime JAMAIS les données existantes : chaque exécution
     AJOUTE un nouveau fichier data/bronze/run_<date>.parquet.
  4. Si l'OCR échoue, le pipeline ne plante pas : on enregistre une ligne avec
     statut = "erreur" et le message, et le fichier sera retraité au prochain lancement.
"""

import hashlib
import sys
import time
from datetime import datetime, timezone

import pandas as pd
from pypdf import PdfReader

import config
from etape1_recuperer import detecter_type
from etape2_ocr import appeler_ocr, page_en_image


def empreinte_sha256(chemin):
    """Calcule l'empreinte sha256 du contenu du fichier (identique si le contenu est identique)."""
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def lire_bronze():
    """Lit toutes les lignes déjà présentes dans la couche bronze (tous les fichiers run_*.parquet)."""
    fichiers = sorted(config.DOSSIER_BRONZE.glob("run_*.parquet"))
    if not fichiers:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(f) for f in fichiers], ignore_index=True)


def extraire_texte_pdf(chemin):
    """PDF « texte » : on lit directement la couche texte de chaque page."""
    lecteur = PdfReader(chemin)
    pages = [page.extract_text() or "" for page in lecteur.pages]
    return "\n\n".join(pages)


def extraire_texte_ocr(chemin, nb_pages):
    """PDF « image » : chaque page est transformée en image puis envoyée au modèle d'OCR."""
    pages = []
    for numero in range(nb_pages):
        image = page_en_image(chemin, numero_page=numero, dpi=config.OCR_DPI)
        pages.append(appeler_ocr(image))
    return "\n\n".join(pages)


def traiter_pdf(chemin):
    """Extrait le texte d'un PDF et renvoie une ligne (dictionnaire) pour la couche bronze."""
    ligne = {
        "sha256": empreinte_sha256(chemin),
        "nom_fichier": chemin.name,
        "taille_octets": chemin.stat().st_size,
        "nb_pages": None,
        "type_pdf": None,           # "texte" ou "image"
        "methode": None,            # "pypdf" ou "ocr"
        "modele_ocr": None,         # nom du modèle d'OCR (si OCR)
        "ocr_dpi": None,            # résolution utilisée (si OCR)
        "texte": None,              # texte brut extrait (Markdown pour l'OCR)
        "duree_s": None,            # temps d'extraction
        "date_ingestion": datetime.now(timezone.utc),
        "statut": None,             # "ok" ou "erreur"
        "erreur": None,             # message d'erreur éventuel
    }

    debut = time.time()
    try:
        ligne["nb_pages"] = len(PdfReader(chemin).pages)
        ligne["type_pdf"] = detecter_type(chemin)

        if ligne["type_pdf"] == "texte":
            ligne["methode"] = "pypdf"
            ligne["texte"] = extraire_texte_pdf(chemin)
        else:
            ligne["methode"] = "ocr"
            ligne["modele_ocr"] = config.OCR_MODELE
            ligne["ocr_dpi"] = config.OCR_DPI
            ligne["texte"] = extraire_texte_ocr(chemin, ligne["nb_pages"])

        ligne["statut"] = "ok"
    except Exception as erreur:
        # OCR indisponible, délai dépassé, PDF illisible... : on trace et on continue
        ligne["statut"] = "erreur"
        ligne["erreur"] = f"{type(erreur).__name__} : {erreur}"[:500]

    ligne["duree_s"] = round(time.time() - debut, 2)
    return ligne


def main(limite=None):
    config.DOSSIER_BRONZE.mkdir(parents=True, exist_ok=True)

    # Empreintes des fichiers déjà ingérés AVEC SUCCÈS (les erreurs seront retentées)
    bronze = lire_bronze()
    deja_ok = set(bronze.loc[bronze["statut"] == "ok", "sha256"]) if len(bronze) else set()

    # PDF à traiter : ceux dont l'empreinte n'est pas encore « ok »
    a_traiter = []
    for chemin in sorted(config.DOSSIER_LANDING.glob("*.pdf")):
        sha = empreinte_sha256(chemin)
        if sha not in deja_ok:
            a_traiter.append(chemin)
            deja_ok.add(sha)  # évite de traiter deux fois deux fichiers au contenu identique
    if limite:
        a_traiter = a_traiter[:limite]

    print(f"{len(a_traiter)} PDF à traiter.")
    if not a_traiter:
        print("Rien de nouveau : aucun appel OCR.")
        return

    lignes = []
    for i, chemin in enumerate(a_traiter, start=1):
        ligne = traiter_pdf(chemin)
        lignes.append(ligne)
        info = ligne["erreur"] if ligne["statut"] == "erreur" else f"{ligne['duree_s']} s"
        print(f"[{i}/{len(a_traiter)}] {chemin.name:40} {ligne['methode'] or '-':6} {ligne['statut']:7} {info}")

    # Nouveau fichier pour cette exécution : les fichiers précédents ne sont jamais modifiés
    horodatage = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sortie = config.DOSSIER_BRONZE / f"run_{horodatage}.parquet"
    pd.DataFrame(lignes).to_parquet(sortie, index=False)

    nb_ok = sum(l["statut"] == "ok" for l in lignes)
    print(f"\n{nb_ok} ok, {len(lignes) - nb_ok} erreur(s) -> {sortie.relative_to(config.DOSSIER_PROJET)}")


if __name__ == "__main__":
    main(limite=int(sys.argv[1]) if len(sys.argv) > 1 else None)
