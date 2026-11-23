"""ÉTAPE 1 — Récupérer les factures et dire si chacune est « texte » ou « image ».

Lancement :  uv run python etape1_recuperer.py

1. Télécharge les PDF du bucket S3 vers data/landing/
   (seulement les nouveaux : un fichier déjà présent n'est pas retéléchargé).
2. Pour chaque PDF, affiche « texte » (couche texte lisible) ou « image » (scan -> OCR).
"""

from pathlib import Path

import boto3
from botocore.config import Config
from pypdf import PdfReader

import config

# Une page avec moins de 20 caractères lisibles est considérée comme une image (scan)
MIN_CARACTERES_PAR_PAGE = 20


def telecharger_factures():
    """Télécharge les PDF du bucket qui ne sont pas encore dans data/landing/."""
    config.DOSSIER_LANDING.mkdir(parents=True, exist_ok=True)

    # Hyperfluid expose une passerelle S3 : le nom du bucket doit rester dans le
    # chemin (/factures/...), sinon boto3 fabrique factures.<endpoint>, que le
    # certificat TLS ne couvre pas (SSLError).
    s3 = boto3.client("s3", config=Config(s3={"addressing_style": "path"}))

    # Liste les objets du bucket (par paquets de 1000 maximum, d'où le « paginator »)
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=config.BUCKET)

    nouveaux = 0
    for page in pages:
        for objet in page.get("Contents", []):
            cle = objet["Key"]
            if not cle.lower().endswith(".pdf"):
                continue

            # On ne garde que le nom du fichier (sécurité : pas de « ../ » dans le chemin)
            destination = config.DOSSIER_LANDING / Path(cle).name

            # Déjà téléchargé (même taille) : on passe
            if destination.exists() and destination.stat().st_size == objet["Size"]:
                continue

            s3.download_file(config.BUCKET, cle, str(destination))
            print("téléchargé :", destination.name)
            nouveaux += 1

    print(f"{nouveaux} nouvelle(s) facture(s) téléchargée(s).\n")


def detecter_type(chemin_pdf):
    """Renvoie "texte" si toutes les pages ont du texte lisible, sinon "image".

    Si une seule page n'a pas de texte (scan, ou PDF mixte), on renvoie "image" :
    mieux vaut un passage OCR de trop qu'une page perdue.
    """
    lecteur = PdfReader(chemin_pdf)
    for page in lecteur.pages:
        texte = page.extract_text() or ""
        nb_caracteres = len(texte.replace(" ", "").replace("\n", ""))
        if nb_caracteres < MIN_CARACTERES_PAR_PAGE:
            return "image"
    return "texte"


def classer_factures():
    """Affiche le type de chaque PDF et le total."""
    total = {"texte": 0, "image": 0, "erreur": 0}
    for chemin in sorted(config.DOSSIER_LANDING.glob("*.pdf")):
        try:
            type_pdf = detecter_type(chemin)
        except Exception as erreur:  # PDF corrompu : on le signale et on continue
            type_pdf = "erreur"
            print(chemin.name, "-> illisible :", erreur)
        total[type_pdf] += 1
        print(f"{chemin.name:40} {type_pdf}")

    print(f"\nTotal : {total['texte']} texte, {total['image']} image, {total['erreur']} erreur")


if __name__ == "__main__":
    telecharger_factures()
    classer_factures()
