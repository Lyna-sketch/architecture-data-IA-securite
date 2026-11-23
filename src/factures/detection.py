"""Étape 1b : déterminer si un PDF a une couche texte exploitable ou s'il faut l'OCR."""

from pathlib import Path
from pypdf import PdfReader

# En dessous de ce nombre de caractères « utiles » (hors espaces), on considère
# qu'une page n'a pas de vraie couche texte. Valeur à ajuster après observation.
MIN_CHARS_PER_PAGE = 20

def page_text_lengths(pdf_path: Path) -> list[int]:
    """Renvoie, pour chaque page, le nombre de caractères non blancs extraits.

    Exemple : [812, 640] pour un PDF texte de 2 pages, [0] pour un scan d'une page.
    """
    reader = PdfReader(pdf_path)
    lengths = []
    for page in reader.pages:
        text = page.extract_text() or ""
        lengths.append(len("".join(text.split())))  # on retire espaces et retours à la ligne
    return lengths


def detect_type(pdf_path: Path) -> str:
    """Renvoie "texte" si le PDF a une couche texte exploitable, "image" sinon.

    Règle : on décide page par page, puis pour le document entier.
      - une page est « texte » si elle contient au moins MIN_CHARS_PER_PAGE caractères ;
      - le document est « texte » seulement si TOUTES ses pages le sont ;
      - dès qu'une page n'a pas de texte (scan, ou PDF mixte), le document est « image »
        et partira à l'OCR : mieux vaut un appel OCR de trop qu'une page perdue.

    Lève ValueError si le PDF n'a aucune page (fichier vide ou corrompu) :
    ce n'est ni du texte ni une image, l'appelant doit traiter ce cas comme une erreur.
    """
    lengths = page_text_lengths(pdf_path)
    if not lengths:
        raise ValueError(f"{pdf_path.name} : aucune page lisible")

    if all(n >= MIN_CHARS_PER_PAGE for n in lengths):
        return "texte"
    return "image"
