"""Étape 1a : télécharger les factures du bucket S3 vers la zone d'arrivée (data/landing/).

Principe incrémental : on liste les objets du bucket et on ne télécharge que ceux
qui ne sont pas déjà présents en local avec la même taille. Relancer la commande
ne retélécharge donc rien.
"""

from pathlib import Path

import boto3
from botocore.config import Config

from factures import config


def s3_client():
    """Crée un client S3.

    boto3 lit automatiquement AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
    AWS_ENDPOINT_URL et AWS_DEFAULT_REGION dans l'environnement (chargé depuis .env).
    L'adressage « path » (https://endpoint/bucket/clé) est le plus compatible avec
    les stockages S3 qui ne sont pas Amazon.
    """
    return boto3.client("s3", config=Config(s3={"addressing_style": "path"}))


def list_pdfs(client) -> list[dict]:
    """Liste tous les PDF du bucket.

    Un appel S3 renvoie au plus 1000 objets : le « paginator » enchaîne les appels
    pour nous si le bucket en contient davantage.
    """
    paginator = client.get_paginator("list_objects_v2")
    objects = []
    for page in paginator.paginate(Bucket=config.S3_BUCKET, Prefix=config.S3_PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].lower().endswith(".pdf"):
                objects.append(obj)
    return objects


def local_path_for(key: str) -> Path:
    """Chemin local d'un objet S3, en ne gardant que le nom du fichier.

    Sécurité : une clé S3 est une chaîne quelconque (« ../../.bashrc » est possible).
    En ne gardant que le nom de fichier, on ne peut jamais écrire hors de landing/.
    """
    return config.LANDING_DIR / Path(key).name


def fetch() -> None:
    config.LANDING_DIR.mkdir(parents=True, exist_ok=True)
    client = s3_client()
    objects = list_pdfs(client)

    downloaded = skipped = 0
    for obj in objects:
        target = local_path_for(obj["Key"])

        # Déjà présent avec la même taille : rien à faire
        if target.exists() and target.stat().st_size == obj["Size"]:
            skipped += 1
            continue

        # On télécharge dans un fichier temporaire puis on le renomme :
        # si le téléchargement est interrompu, on ne laisse pas de PDF à moitié écrit
        # qui serait pris pour un fichier complet au prochain lancement.
        tmp = target.with_suffix(".part")
        client.download_file(config.S3_BUCKET, obj["Key"], str(tmp))
        tmp.replace(target)
        downloaded += 1
        print(f"  téléchargé : {target.name}")

    print(
        f"{len(objects)} PDF dans s3://{config.S3_BUCKET}/{config.S3_PREFIX} — "
        f"{downloaded} téléchargé(s), {skipped} déjà présent(s)."
    )
