"""Point d'entrée en ligne de commande : `uv run factures <commande>`.

Commandes disponibles :
  fetch     télécharge les nouvelles factures du bucket S3 vers data/landing/
  classify  indique pour chaque PDF de data/landing/ s'il est « texte » ou « image »
"""

import argparse

from factures import config


def cmd_fetch(_args) -> None:
    from factures.fetch import fetch

    fetch()


def cmd_classify(_args) -> None:
    from factures.detection import detect_type, page_text_lengths

    pdfs = sorted(config.LANDING_DIR.glob("*.pdf"))
    if not pdfs:
        print("Aucun PDF dans data/landing/ : lancez d'abord `uv run factures fetch`.")
        return

    counts = {"texte": 0, "image": 0, "erreur": 0}
    print(f"{'fichier':40} {'type':6}  caractères par page")
    for pdf in pdfs:
        # Un PDF corrompu ne doit pas arrêter tout le traitement : on le signale et on continue.
        try:
            kind = detect_type(pdf)
            detail = page_text_lengths(pdf)
        except Exception as exc:
            kind, detail = "erreur", exc
        counts[kind] += 1
        print(f"{pdf.name:40} {kind:6}  {detail}")
    print(
        f"\nTotal : {len(pdfs)} PDF — {counts['texte']} texte, "
        f"{counts['image']} image, {counts['erreur']} erreur"
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="factures", description="Pipeline factures")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch", help="télécharge les nouvelles factures depuis S3").set_defaults(func=cmd_fetch)
    sub.add_parser("classify", help="classe chaque PDF en texte / image").set_defaults(func=cmd_classify)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
