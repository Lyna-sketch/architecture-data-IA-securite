# architecture-data-IA-securite

De la facture PDF (native ou scannée) à un agent IA qui répond aux questions sur les factures :

```
PDF (bucket S3) ─► extraction / OCR ─► bronze ─► silver ─► entrepôt DuckDB ─► serveur MCP ─► agent IA
```

## Installation

1. Installer [uv](https://docs.astral.sh/uv/) (gestionnaire Python : installe Python et les dépendances) :

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Installer les dépendances du projet :

   ```bash
   uv sync
   ```

3. Créer le fichier de configuration et y coller vos clés (ce fichier n'est jamais commité) :

   ```bash
   cp .env.example .env
   ```

## Utilisation

| Commande | Rôle |
|---|---|
| `uv run factures fetch` | télécharge les nouvelles factures du bucket vers `data/landing/` |
| `uv run factures classify` | indique pour chaque PDF s'il est « texte » ou « image » (scan) |

## Organisation du code

```
src/factures/
  config.py     configuration (lue depuis .env)
  fetch.py      téléchargement S3 incrémental
  detection.py  détection texte / image
  cli.py        commandes `factures ...`
```
