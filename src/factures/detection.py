"""Étape 1b : déterminer si un PDF a une couche texte exploitable ou s'il faut l'OCR.

>>> À COMPLÉTER PAR VOUS : la fonction `detect_type`. <<<
"""

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

    À vous de jouer ! Indications :
      1. Appelez `page_text_lengths(pdf_path)` pour obtenir la liste des longueurs.
      2. Une page est « texte » si sa longueur >= MIN_CHARS_PER_PAGE.
      3. Décidez d'une règle pour le PDF entier. Questions à vous poser :
           - et si le PDF a 0 page (fichier vide ou corrompu) ?
           - et si certaines pages sont texte et d'autres non (PDF mixte) ?
             Le plus prudent : "texte" seulement si TOUTES les pages sont texte,
             sinon "image" (on enverra le document à l'OCR plutôt que de perdre une page).
      4. Renvoyez la chaîne "texte" ou "image".
    """
    raise NotImplementedError("detect_type n'est pas encore écrite — à vous !")
