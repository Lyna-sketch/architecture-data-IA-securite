"""ÉTAPE 2 — Envoyer une page de facture au modèle d'OCR LightOnOCR-3 et afficher le résultat.

Lancement :  uv run python etape2_ocr.py facture_P-2025-0002_scan.pdf
             uv run python etape2_ocr.py facture_P-2025-0002_scan.pdf 200   (autre résolution, en DPI)

Recommandations de la fiche du modèle (https://huggingface.co/lightonai/LightOnOCR-3-1B) :
  - image dont le plus grand côté fait 1540 pixels, sans déformation.
    Nos factures sont toutes en A4 (29,7 cm de haut) : 130 DPI donne 1520 px de haut,
    soit la taille recommandée. (La fiche cite aussi 200 DPI, qui donne 2339 px.) ;
  - requête au format « OpenAI chat completions » contenant UNIQUEMENT l'image
    (pas de consigne texte : le modèle n'a pas été entraîné pour ça) ;
  - temperature 0.2, top_p 0.9, max_tokens 4096.

Changer de fournisseur d'OCR : seule la fonction `appeler_ocr` est à réécrire ;
le reste du projet ne fait que l'appeler.
"""

import base64
import io
import sys
import time

import pypdfium2
import requests

import config


def page_en_image(chemin_pdf, numero_page=0, dpi=config.OCR_DPI):
    """Transforme une page du PDF en image PNG à la résolution `dpi` (points par pouce)."""
    pdf = pypdfium2.PdfDocument(chemin_pdf)
    page = pdf[numero_page]

    # Un PDF mesure ses pages en « points » : 72 points = 1 pouce.
    # Pour obtenir `dpi` pixels par pouce, on agrandit donc la page de dpi / 72.
    zoom = dpi / 72
    image = page.render(scale=zoom).to_pil()
    pdf.close()

    # Conversion de l'image en octets PNG
    tampon = io.BytesIO()
    image.save(tampon, format="PNG")
    return tampon.getvalue()


def appeler_ocr(image_png):
    """Envoie une image au modèle d'OCR et renvoie le texte reconnu (Markdown)."""
    image_base64 = base64.b64encode(image_png).decode()

    requete = {
        "model": config.OCR_MODELE,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + image_base64}}
                ],
            }
        ],
        "max_tokens": 4096,
        "temperature": 0.2,
        "top_p": 0.9,
    }

    reponse = requests.post(
        config.OCR_URL.rstrip("/") + "/chat/completions",
        json=requete,
        headers={"Authorization": "Bearer " + config.OCR_CLE},
        timeout=120,
    )
    reponse.raise_for_status()  # lève une erreur si le serveur répond 4xx / 5xx
    texte = reponse.json()["choices"][0]["message"]["content"]

    # Une réponse vide n'est pas un résultat : c'est une erreur (le document sera retraité)
    if not texte or not texte.strip():
        raise ValueError("réponse vide du modèle d'OCR")
    return texte


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage : uv run python etape2_ocr.py <nom_du_pdf> [dpi]")
        sys.exit(1)

    chemin = config.DOSSIER_LANDING / sys.argv[1]
    dpi = int(sys.argv[2]) if len(sys.argv) > 2 else config.OCR_DPI

    image = page_en_image(chemin, dpi=dpi)

    debut = time.time()
    texte = appeler_ocr(image)
    duree = time.time() - debut

    print(texte)
    print("-" * 50)
    print(f"Résolution : {dpi} DPI  |  temps OCR : {duree:.1f} s pour 1 page")
