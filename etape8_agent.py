"""ÉTAPE 8 — Agent IA : répond en français aux questions sur les factures, avec les outils MCP.

Lancement :
    uv run python etape8_agent.py                         conversation, avec le LLM par défaut (LLM_PROFIL)
    uv run python etape8_agent.py --llm ollama            conversation avec un autre LLM (profil « ollama »)
    uv run python etape8_agent.py --llm ollama -q "..."   une seule question, puis arrêt

LLM interchangeable par CONFIGURATION : chaque LLM est un « profil » décrit dans .env
    <PROFIL>_BASE_URL   adresse d'une API compatible OpenAI (Hyperfluid/vLLM, Ollama, OpenAI, Anthropic...)
    <PROFIL>_API_KEY    clé d'API
    <PROFIL>_MODEL      nom du modèle
(même convention que OCR_BASE_URL / OCR_API_KEY / OCR_MODEL). Le code ne change jamais :
seul le profil choisi change.

L'agent n'a accès aux données QUE par les outils du serveur MCP (etape7_mcp.py),
et il affiche chaque outil appelé, les requêtes SQL exécutées et un aperçu du résultat.
"""

import argparse
import asyncio
import datetime
import json
import os
import re
import sys
import time

from mcp import Client, StdioServerParameters
from openai import OpenAI

import config

MAX_ETAPES = 8  # nombre maximum d'appels au LLM pour une question (évite les boucles infinies)

CONSIGNE_SYSTEME = f"""Tu es un assistant qui répond en français aux questions sur les factures fournisseurs
d'une entreprise. Nous sommes le {datetime.date.today():%d/%m/%Y}.

Règles impératives :
- Tu n'as accès aux données QUE par les outils fournis. Pour toute question sur les factures, appelle un outil.
- N'invente JAMAIS un chiffre : chaque nombre, montant ou date de ta réponse doit venir du résultat d'un outil.
- Pour un nombre de factures ou une somme, utilise totaux_factures : ne fais pas l'addition toi-même.
- Si les outils ne permettent pas de répondre, dis-le simplement.
- Les montants sont en euros ; écris-les au format français (ex. 106 886,43 €).
- Réponds de façon courte et précise, et indique les filtres utilisés (période, statut...)."""


# ---------------------------------------------------------------------------
# Configuration du LLM (profil)
# ---------------------------------------------------------------------------

def charger_llm(profil):
    """Lit la configuration d'un profil de LLM dans .env et renvoie (client, nom du modèle)."""
    p = profil.upper()
    url, cle, modele = (os.getenv(f"{p}_BASE_URL"), os.getenv(f"{p}_API_KEY"), os.getenv(f"{p}_MODEL"))
    manquants = [n for n, v in [(f"{p}_BASE_URL", url), (f"{p}_MODEL", modele)] if not v]
    if manquants:
        sys.exit(f"Profil de LLM « {profil} » incomplet dans .env : {', '.join(manquants)}")
    return OpenAI(base_url=url, api_key=cle or "pas-de-cle"), modele


def outils_pour_llm(outils_mcp):
    """Traduit la description des outils MCP au format « function calling » attendu par le LLM."""
    return [{"type": "function",
             "function": {"name": o.name, "description": o.description, "parameters": o.input_schema}}
            for o in outils_mcp]


# ---------------------------------------------------------------------------
# Affichage
# ---------------------------------------------------------------------------

def nettoyer(texte):
    """Retire les balises de « raisonnement interne » que certains modèles laissent dans la réponse
    (Gemma : <|channel>thought ... <channel|> ; Qwen, DeepSeek : <think> ... </think>)."""
    texte = re.sub(r"<\|channel>.*?<channel\|>", "", texte or "", flags=re.DOTALL)
    texte = re.sub(r"<think>.*?</think>", "", texte, flags=re.DOTALL)
    return texte.strip()


def afficher_appel(nom, arguments, resultat):
    """Montre à l'utilisateur ce que fait l'agent : outil, arguments, SQL et aperçu du résultat."""
    print(f"  🔧 {nom}({json.dumps(arguments, ensure_ascii=False)})")
    for sql in resultat.get("sql") or []:
        print(f"     SQL : {sql}")
    if resultat.get("parametres"):
        print(f"     paramètres : {resultat['parametres']}")
    if "erreur" in resultat:
        print(f"     ⚠ erreur : {resultat['erreur']}")
        return
    apercu = {k: v for k, v in resultat.items() if k not in ("sql", "parametres")}
    texte = json.dumps(apercu, ensure_ascii=False)
    print(f"     résultat : {texte[:300]}{' …' if len(texte) > 300 else ''}")


# ---------------------------------------------------------------------------
# Boucle de l'agent
# ---------------------------------------------------------------------------

async def repondre(llm, modele, outils, client_mcp, messages):
    """Traite la dernière question de `messages` : appels d'outils successifs, puis réponse finale."""
    for _ in range(MAX_ETAPES):
        reponse = llm.chat.completions.create(model=modele, messages=messages, tools=outils, temperature=0)
        message = reponse.choices[0].message

        if not message.tool_calls:  # pas d'outil demandé : c'est la réponse finale
            texte = nettoyer(message.content)
            messages.append({"role": "assistant", "content": texte})
            return texte or "(réponse vide)"

        # Le LLM demande un ou plusieurs outils : on les exécute via le serveur MCP
        messages.append({"role": "assistant", "content": message.content or "",
                         "tool_calls": [appel.model_dump() for appel in message.tool_calls]})
        for appel in message.tool_calls:
            try:
                arguments = json.loads(appel.function.arguments or "{}")
                resultat_mcp = await client_mcp.call_tool(appel.function.name, arguments)
                texte = resultat_mcp.content[0].text
                resultat = json.loads(texte)
            except Exception as e:  # arguments illisibles, outil inconnu... : on le dit au LLM
                arguments = appel.function.arguments
                resultat = {"erreur": f"Appel d'outil impossible : {e}"}
                texte = json.dumps(resultat, ensure_ascii=False)
            afficher_appel(appel.function.name, arguments, resultat)
            messages.append({"role": "tool", "tool_call_id": appel.id, "content": texte})

    return f"(arrêt : plus de {MAX_ETAPES} étapes sans réponse finale)"


async def main():
    parser = argparse.ArgumentParser(description="Agent IA sur les factures")
    parser.add_argument("--llm", default=os.getenv("LLM_PROFIL", "gemma"),
                        help="profil de LLM défini dans .env (défaut : LLM_PROFIL)")
    parser.add_argument("-q", "--question", help="poser une seule question puis s'arrêter")
    args = parser.parse_args()

    llm, modele = charger_llm(args.llm)
    serveur = StdioServerParameters(command=sys.executable, args=["etape7_mcp.py"],
                                    cwd=str(config.DOSSIER_PROJET))

    async with Client(serveur) as client_mcp:
        outils = outils_pour_llm((await client_mcp.list_tools()).tools)
        print(f"Agent factures — LLM : {modele} (profil « {args.llm} ») — {len(outils)} outils MCP")
        messages = [{"role": "system", "content": CONSIGNE_SYSTEME}]  # l'historique garde le fil

        while True:
            if args.question:
                question = args.question
                print(f"\nVous > {question}")
            else:
                try:
                    question = input("\nVous > ").strip()
                except (EOFError, KeyboardInterrupt):  # Ctrl+D ou Ctrl+C : arrêt propre
                    question = "quitter"
            if question.lower() in ("quitter", "exit", "quit", "/q"):
                print("Au revoir.")
                break
            if not question:
                continue

            messages.append({"role": "user", "content": question})
            debut = time.time()
            try:
                texte = await repondre(llm, modele, outils, client_mcp, messages)
            except Exception as e:  # LLM injoignable, quota... : on l'affiche sans planter
                texte = f"(erreur du LLM : {type(e).__name__} : {e})"
                messages.pop()  # on retire la question restée sans réponse
            print(f"\nAgent > {texte}\n  ({time.time() - debut:.1f} s)")

            if args.question:
                break
    # En sortant du bloc « async with », le serveur MCP est arrêté proprement.


if __name__ == "__main__":
    asyncio.run(main())
