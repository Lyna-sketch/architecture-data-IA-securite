"""ÉTAPE 4 — Couche silver : des tables propres, typées et contrôlées.

Lancement :  uv run python etape4_silver.py

Lit la couche bronze et produit dans data/silver/ :
  - factures.parquet        une ligne par facture (avec un statut de qualité)
  - lignes_facture.parquet  une ligne par ligne de facture
  - quarantaine.parquet     les documents rejetés, avec le motif du rejet

Le silver est entièrement RECALCULÉ à partir du bronze à chaque lancement :
si on améliore le parseur, il suffit de relancer ce script (sans refaire d'OCR).
"""

import re
from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import config
from etape3_bronze import lire_bronze

CENTIME = Decimal("0.01")


# ---------------------------------------------------------------------------
# 1. Normalisation : ramener pypdf et OCR (Markdown + HTML) à « une info par ligne »
# ---------------------------------------------------------------------------

def normaliser(texte):
    """Transforme le texte brut en une liste de lignes propres, quelle que soit la source."""
    t = re.sub(r"<[^>]+>", "\n", texte)                     # balises HTML (<td>...) -> retour à la ligne
    t = t.replace("|", "\n")                                # cellules d'un éventuel tableau Markdown
    t = t.replace("**", "").replace("#", "")                # gras et titres Markdown
    t = t.replace(" ", " ").replace("\xa0", " ")       # espaces insécables -> espaces normaux
    lignes = [ligne.strip() for ligne in t.split("\n")]
    return [l for l in lignes if l and not re.fullmatch(r"[-: ]+", l)]  # retire lignes vides et « --- »


# ---------------------------------------------------------------------------
# 2. Conversion des valeurs (texte -> types)
# ---------------------------------------------------------------------------

def en_montant(texte):
    """ "1 263,00 €" -> Decimal("1263.00"). Renvoie None si ce n'est pas un montant.

    Decimal et non float : 0.1 + 0.2 vaut 0.30000000000000004 en float,
    inacceptable pour de l'argent. Decimal calcule exactement au centime.
    """
    if texte and re.fullmatch(r"-?\d[\d ]*,\d{2} ?€?", texte.strip()):
        return Decimal(texte.replace(" ", "").replace("€", "").replace(",", "."))
    return None


def en_date(texte):
    """ "28/06/2025" -> date(2025, 6, 28). Renvoie None si la date est invalide."""
    try:
        return datetime.strptime(texte.strip(), "%d/%m/%Y").date()
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# 3. Extraction des champs
# ---------------------------------------------------------------------------

def champ(lignes, libelle):
    """Valeur d'une ligne « Libellé : valeur » (ex. « Numéro de facture : P-2025-0002 »)."""
    for ligne in lignes:
        m = re.match(re.escape(libelle) + r"\s*:\s*(.+)$", ligne)
        if m:
            return m.group(1).strip()
    return None


def total(lignes, libelle):
    """Montant qui suit un libellé de total, sur la même ligne OU sur la suivante.

    On garde le DERNIER montant trouvé : « Total HT » apparaît aussi comme en-tête
    de colonne du tableau, mais il n'est alors pas suivi d'un montant.
    """
    trouve = None
    for i, ligne in enumerate(lignes):
        if ligne == libelle or ligne.startswith(libelle + " "):
            reste = ligne[len(libelle):].strip()
            suivante = lignes[i + 1] if i + 1 < len(lignes) else None
            montant = en_montant(reste) if reste else en_montant(suivante)
            if montant is not None:
                trouve = montant
    return trouve


def lignes_de_facture(lignes):
    """Lit le tableau : après l'en-tête (Désignation, Qté, Prix unitaire HT, TVA, Total HT),
    les cellules arrivent par groupes de 5 jusqu'à la ligne « Total HT »."""
    if "Désignation" not in lignes:
        return []
    i = lignes.index("Désignation") + 5
    resultat = []
    while i + 4 < len(lignes) and not lignes[i].startswith("Total HT"):
        designation, qte, pu, tva, tot = lignes[i:i + 5]
        resultat.append({
            "designation": designation,
            "quantite": int(qte) if qte.isdigit() else None,
            "prix_unitaire_ht": en_montant(pu),
            "taux_tva": Decimal(tva.replace("%", "").replace(",", ".").strip()) if re.fullmatch(r"[\d,]+ ?%", tva) else None,
            "total_ht": en_montant(tot),
        })
        i += 5
    return resultat


def parser_facture(texte):
    """Texte brut d'une facture -> (dictionnaire facture, liste des lignes)."""
    lignes = normaliser(texte)
    facture = {
        # Le fournisseur est la première ligne de la facture (hors titre « FACTURE »)
        "fournisseur": next((l for l in lignes if l.upper() != "FACTURE"), None),
        "siret_fournisseur": champ(lignes, "SIRET"),
        "numero_facture": champ(lignes, "Numéro de facture"),
        "date_emission": en_date(champ(lignes, "Date d'émission")),
        "date_echeance": en_date(champ(lignes, "Date d'échéance")),
        "categorie": champ(lignes, "Catégorie"),
        "statut_paiement": champ(lignes, "Statut"),
        "client": champ(lignes, "Client"),
        "siret_client": champ(lignes, "SIRET client"),
        "mode_paiement": champ(lignes, "Mode de paiement"),
        "total_ht": total(lignes, "Total HT"),
        "total_tva": total(lignes, "Total TVA"),
        "total_ttc": total(lignes, "Total TTC"),
    }
    return facture, lignes_de_facture(lignes)


# ---------------------------------------------------------------------------
# 4. Contrôles qualité
# ---------------------------------------------------------------------------

OBLIGATOIRES = ["numero_facture", "fournisseur", "date_emission", "total_ht", "total_tva", "total_ttc"]


def motif_de_rejet(facture):
    """Facture INEXPLOITABLE -> renvoie le motif (elle ira en quarantaine). Sinon None."""
    manquants = [c for c in OBLIGATOIRES if facture[c] is None]
    if manquants:
        return "champ(s) obligatoire(s) manquant(s) ou illisible(s) : " + ", ".join(manquants)
    return None


def anomalies(facture, lignes):
    """Facture exploitable mais SUSPECTE -> liste des anomalies (elle sera « signalée »)."""
    pb = []
    if facture["total_ht"] + facture["total_tva"] != facture["total_ttc"]:
        pb.append(f"HT + TVA ({facture['total_ht'] + facture['total_tva']}) != TTC ({facture['total_ttc']})")
    if not lignes:
        pb.append("aucune ligne de facture lue")
    elif any(l[k] is None for l in lignes for k in l):
        pb.append("ligne(s) de facture illisible(s)")
    else:
        somme = sum(l["total_ht"] for l in lignes)
        if somme != facture["total_ht"]:
            pb.append(f"somme des lignes ({somme}) != total HT ({facture['total_ht']})")
        for n, l in enumerate(lignes, start=1):
            attendu = (l["quantite"] * l["prix_unitaire_ht"]).quantize(CENTIME)
            if attendu != l["total_ht"]:
                pb.append(f"ligne {n} : {l['quantite']} x {l['prix_unitaire_ht']} != {l['total_ht']}")
    if facture["date_echeance"] and facture["date_echeance"] < facture["date_emission"]:
        pb.append("date d'échéance antérieure à la date d'émission")
    for c in ("siret_fournisseur", "siret_client"):
        if not re.fullmatch(r"\d{14}", facture[c] or ""):
            pb.append(f"{c} invalide (14 chiffres attendus) : {facture[c]}")
    return pb


# ---------------------------------------------------------------------------
# 5. Programme principal
# ---------------------------------------------------------------------------

# Types des colonnes : dates en date, montants en décimal exact (12 chiffres dont 2 après la virgule)
MONTANT = pa.decimal128(12, 2)
SCHEMA_FACTURES = pa.schema([
    ("numero_facture", pa.string()), ("fournisseur", pa.string()), ("siret_fournisseur", pa.string()),
    ("client", pa.string()), ("siret_client", pa.string()),
    ("date_emission", pa.date32()), ("date_echeance", pa.date32()),
    ("categorie", pa.string()), ("statut_paiement", pa.string()), ("mode_paiement", pa.string()),
    ("total_ht", MONTANT), ("total_tva", MONTANT), ("total_ttc", MONTANT), ("nb_lignes", pa.int32()),
    ("statut_qualite", pa.string()), ("anomalies", pa.string()),
    ("source_sha256", pa.string()), ("source_fichier", pa.string()), ("methode_extraction", pa.string()),
])
SCHEMA_LIGNES = pa.schema([
    ("numero_facture", pa.string()), ("num_ligne", pa.int32()), ("designation", pa.string()),
    ("quantite", pa.int32()), ("prix_unitaire_ht", MONTANT), ("taux_tva", pa.decimal128(5, 2)),
    ("total_ht", MONTANT), ("source_sha256", pa.string()),
])
SCHEMA_QUARANTAINE = pa.schema([
    ("source_sha256", pa.string()), ("source_fichier", pa.string()), ("numero_facture", pa.string()),
    ("motif", pa.string()), ("date_rejet", pa.timestamp("us", tz="UTC")),
])


def ecrire(lignes, schema, nom):
    table = pa.Table.from_pylist(lignes, schema=schema)
    pq.write_table(table, config.DOSSIER_SILVER / nom)


def main():
    config.DOSSIER_SILVER.mkdir(parents=True, exist_ok=True)

    # Une seule ligne « ok » par document (sha256), dans l'ordre d'arrivée
    bronze = lire_bronze()
    bronze = bronze[bronze["statut"] == "ok"].sort_values("date_ingestion").drop_duplicates("sha256")

    factures, lignes_sortie, quarantaine = [], [], []
    deja_vues = set()  # (fournisseur, numéro) des factures déjà acceptées -> détection des doublons
    maintenant = datetime.now(timezone.utc)

    for doc in bronze.itertuples():
        facture, lignes = parser_facture(doc.texte)
        cle = (facture["fournisseur"], facture["numero_facture"])

        motif = motif_de_rejet(facture)
        if motif is None and cle in deja_vues:
            motif = f"doublon : facture {facture['numero_facture']} de {facture['fournisseur']} déjà présente"
        if motif:
            quarantaine.append({"source_sha256": doc.sha256, "source_fichier": doc.nom_fichier,
                                "numero_facture": facture["numero_facture"], "motif": motif,
                                "date_rejet": maintenant})
            continue

        deja_vues.add(cle)
        pb = anomalies(facture, lignes)
        factures.append({**facture, "nb_lignes": len(lignes),
                         "statut_qualite": "signalee" if pb else "valide",
                         "anomalies": " ; ".join(pb) or None,
                         "source_sha256": doc.sha256, "source_fichier": doc.nom_fichier,
                         "methode_extraction": doc.methode})
        for n, l in enumerate(lignes, start=1):
            lignes_sortie.append({"numero_facture": facture["numero_facture"], "num_ligne": n,
                                  **l, "source_sha256": doc.sha256})

    ecrire(factures, SCHEMA_FACTURES, "factures.parquet")
    ecrire(lignes_sortie, SCHEMA_LIGNES, "lignes_facture.parquet")
    ecrire(quarantaine, SCHEMA_QUARANTAINE, "quarantaine.parquet")

    nb_signalees = sum(f["statut_qualite"] == "signalee" for f in factures)
    print(f"{len(bronze)} documents lus dans le bronze")
    print(f"  -> {len(factures)} factures en silver ({len(factures) - nb_signalees} valides, {nb_signalees} signalées)")
    print(f"  -> {len(lignes_sortie)} lignes de facture")
    print(f"  -> {len(quarantaine)} document(s) en quarantaine")
    for f in factures:
        if f["anomalies"]:
            print(f"     signalée  {f['source_fichier']:32} {f['anomalies']}")
    for q in quarantaine:
        print(f"     rejetée   {q['source_fichier']:32} {q['motif']}")


if __name__ == "__main__":
    main()
